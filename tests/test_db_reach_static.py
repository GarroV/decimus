"""Каждое чтение стоит на охвате — сверка по тексту запросов, без базы (#340, Н38).

Запрос по проверкам без условия охвата — дыра границы пространств, видимая
только чтением кода: тест на двух партнёрах её не заметит, если забытый запрос
на них не позвали. Поэтому сверка идёт по ВСЕМ текстам запросов модулей
чтения, а не по вызовам. Без базы и без `requires_db`: пропущенная проверка —
непроверенная проверка.

Условие вписано в каждый запрос литералом (S608: текст SQL не собирается
строкой), и сверяется, что литерал везде один и тот же — `REACH_SQL` для
проверок и `UNIT_REACH_SQL` для справочника (Н39).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import ModuleType

from src.db import directory, move, previews, queries, reports
from src.db.reach import REACH_SQL, UNIT_REACH_SQL

#: Запросы по проверкам без условия охвата — только по имени и с причиной.
ВНЕ_ОХВАТА: dict[str, str] = {
    "queries._PREVIOUS_INSPECTION_SQL": (
        "повтор ×2 (D255) считается по проверкам своего пространства, "
        "и зовёт его бот пишущего тенанта, а не читающий охват"
    ),
    "queries._FINDINGS_OF_INSPECTION_SQL": (
        "читается тем же соединением сразу после карточки, которую "
        "`_GET_INSPECTION_SQL` уже отобрал по охвату; находка чужой проверке "
        "принадлежать не может — внешний ключ"
    ),
}

#: Запросы к справочнику без условия охвата — только по имени и с причиной.
СПРАВОЧНИК_ВНЕ_ОХВАТА: dict[str, str] = {
    "directory._RESOLVE_SQL": (
        "разрешение написания точки в справочнике НАЗВАННОГО тенанта при сливе "
        "и заведении синонимов — запись, а не чтение по охвату"
    ),
}

_ПРОВЕРКИ = re.compile(r"\b(from|join)\s+inspections\s+i\b")
_СПРАВОЧНИК = re.compile(r"\bfrom\s+units\s+u\b")


def _запросы(*модули: ModuleType) -> dict[str, str]:
    return {
        f"{м.__name__.rsplit('.', 1)[-1]}.{имя}": " ".join(текст.split())
        for м in модули
        for имя, текст in vars(м).items()
        if isinstance(текст, str) and имя.endswith("_SQL")
    }


def test_каждое_чтение_проверок_стоит_на_охвате() -> None:
    """Запрос по проверкам без `REACH_SQL` — дыра границы, видимая только чтением."""
    запросы = _запросы(queries, reports, previews, move)
    сверено = [имя for имя, текст in запросы.items() if _ПРОВЕРКИ.search(текст)]
    assert len(сверено) >= 12, f"сверка не нашла запросов — регулярное выражение сломано: {сверено}"
    дыры = [имя for имя in сверено if имя not in ВНЕ_ОХВАТА and REACH_SQL not in запросы[имя]]
    assert дыры == [], "читают проверки без охвата: " + ", ".join(дыры)


def test_каждое_чтение_справочника_стоит_на_охвате() -> None:
    запросы = _запросы(queries, directory)
    сверено = [имя for имя, текст in запросы.items() if _СПРАВОЧНИК.search(текст)]
    assert len(сверено) >= 4, f"сверка не нашла запросов справочника: {сверено}"
    дыры = [
        имя
        for имя in сверено
        if имя not in СПРАВОЧНИК_ВНЕ_ОХВАТА and UNIT_REACH_SQL not in запросы[имя]
    ]
    assert дыры == [], "читают справочник без охвата: " + ", ".join(дыры)


def test_исключения_называют_настоящие_запросы() -> None:
    """Исключение на запрос, которого больше нет, молча расширило бы будущий."""
    запросы = _запросы(queries, reports, previews, move, directory)
    мёртвые = [имя for имя in (*ВНЕ_ОХВАТА, *СПРАВОЧНИК_ВНЕ_ОХВАТА) if имя not in запросы]
    assert мёртвые == []


def test_условие_охвата_записано_одной_строкой() -> None:
    """Сверка идёт по тексту с нормализованными пробелами — и сам литерал обязан быть таким."""
    for литерал in (REACH_SQL, UNIT_REACH_SQL):
        assert литерал == " ".join(литерал.split())


def test_строка_вместо_охвата_это_отказ() -> None:
    """Вызов по-старому, `reach="HQ"`, — отказ до базы, а не чтение по случайности."""
    import pytest

    from src.db.errors import DbError

    with pytest.raises(DbError, match="охват"):
        queries.list_inspections(reach="HQ")  # type: ignore[arg-type]
    with pytest.raises(DbError, match="охват"):
        directory.list_units(reach="GE")  # type: ignore[arg-type]


#: Чтения по идентификатору проверки без охвата: допустимы ТОЛЬКО после того,
#: как карточку той же проверки отобрал `_GET_INSPECTION_SQL` (п.4 ревью #340).
_БЕЗ_ОХВАТА_ПОСЛЕ_КАРТОЧКИ = ("_FINDINGS_OF_INSPECTION_SQL", "_INFO_OF_INSPECTION_SQL")


def _вызовы_execute(узел: ast.AST) -> list[tuple[int, str]]:
    """`(строка, имя запроса)` каждого `cur.execute(<ИМЯ>_SQL, …)` внутри узла."""
    return [
        (вызов.lineno, вызов.args[0].id)
        for вызов in ast.walk(узел)
        if isinstance(вызов, ast.Call)
        and isinstance(вызов.func, ast.Attribute)
        and вызов.func.attr == "execute"
        and вызов.args
        and isinstance(вызов.args[0], ast.Name)
    ]


def test_находки_по_идентификатору_читаются_только_после_карточки_по_охвату() -> None:
    """Исключение из охвата держится на одном вызывающем — второй его бы прорвал.

    Находки и сведения проверки читаются по её идентификатору без `REACH_SQL`,
    потому что единственный вызывающий, `get_inspection`, тем же курсором уже
    отобрал карточку по охвату и вышел, если её нет. Новый вызов этих запросов
    где-либо ещё — чтение чужой проверки по перебору идентификаторов.
    """
    корень = Path(queries.__file__).resolve().parents[2] / "src"
    чужие = [
        str(путь.relative_to(корень.parent))
        for путь in корень.rglob("*.py")
        if путь.name != "queries.py" or путь.parent.name != "db"
        if any(имя in путь.read_text(encoding="utf-8") for имя in _БЕЗ_ОХВАТА_ПОСЛЕ_КАРТОЧКИ)
    ]
    assert чужие == [], "запросы без охвата зовут вне queries.py: " + ", ".join(чужие)

    дерево = ast.parse(Path(queries.__file__).read_text(encoding="utf-8"))
    функции = {у.name: у for у in ast.walk(дерево) if isinstance(у, ast.FunctionDef)}
    зовущие = sorted(
        имя
        for имя, функция in функции.items()
        if any(запрос in _БЕЗ_ОХВАТА_ПОСЛЕ_КАРТОЧКИ for _, запрос in _вызовы_execute(функция))
    )
    assert зовущие == ["get_inspection"], f"запросы без охвата зовут: {зовущие}"

    вызовы = _вызовы_execute(функции["get_inspection"])
    карточка = [строка for строка, запрос in вызовы if запрос == "_GET_INSPECTION_SQL"]
    assert len(карточка) == 1, "get_inspection больше не читает карточку по охвату"
    выход = [
        у.lineno
        for у in ast.walk(функции["get_inspection"])
        if isinstance(у, ast.If)
        and isinstance(у.body[0], ast.Return)
        and isinstance(у.test, ast.Compare)
        and isinstance(у.test.ops[0], ast.Is)
    ]
    assert выход and min(выход) > карточка[0], "нет выхода `if row is None: return` после карточки"
    раньше = [
        запрос
        for строка, запрос in вызовы
        if запрос in _БЕЗ_ОХВАТА_ПОСЛЕ_КАРТОЧКИ and строка < min(выход)
    ]
    assert раньше == [], "читают до проверки карточки по охвату: " + ", ".join(раньше)
