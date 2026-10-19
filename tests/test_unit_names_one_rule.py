"""D538 на границах дверей: MCP-чтение, списки и разбор страниц сайтов.

Правило имени — `domain/unit_resolve.py` (его тесты — `test_domain_unit_resolve.py`); бот,
мини-апп и админка проверены в своих файлах. Здесь — то, что без базы проверяется на границе:
чтение по имени (MCP, экраны) идёт через общий поиск, а каждый список справочника прячет
снятые точки. База-зависимые проверки — `test_db_units_merged_into.py`.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from src.db import directory, prescriptions, queries, unit_profiles
from src.db.reach import Reach

ФИЛЬТР = "merged_into is null"


class _Курсор:
    """Курсор-двойник: отвечает на поиск по справочнику и записывает запрос списка."""

    description: list[Any] = []  # noqa: RUF012

    def __init__(self, журнал: list[dict[str, Any]]) -> None:
        self.журнал = журнал
        self.ответ: list[tuple[Any, ...]] = []

    def __enter__(self) -> _Курсор:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        if sql == directory._LIVE_NAME_SQL:
            self.ответ = []  # точного живого имени нет — идёт общий поиск
        elif sql == directory._DIRECTORY_SQL:
            self.ответ = [
                ("t1", "Tbilisi-1", None, True, ["Tbilisi 1"]),
                ("c1", "Тбилиси-1", "t1", False, []),
            ]
        else:
            self.журнал.append(dict(params))
            self.ответ = []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.ответ[0] if self.ответ else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.ответ


class _Подключение:
    def __init__(self, журнал: list[dict[str, Any]]) -> None:
        self.журнал = журнал

    def cursor(self) -> _Курсор:
        return _Курсор(self.журнал)


@pytest.fixture
def запросы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    журнал: list[dict[str, Any]] = []

    @contextmanager
    def чтение(_что: str, **_: Any) -> Any:
        yield _Подключение(журнал)

    monkeypatch.setattr(queries, "_reading", чтение)
    return журнал


@pytest.mark.parametrize("написано", ["Тбилиси-1", "тбилиси 1", "Tbilisi 1", "Тбилиси -1"])
def test_mcp_чтение_по_имени_идёт_через_общий_поиск(
    запросы: list[dict[str, Any]], написано: str
) -> None:
    # Act — так зовут `list_inspections` / `unit_history` инструментов MCP.
    queries.list_inspections(reach=Reach("HQ", None, None), unit=написано)

    # Assert — в запрос ушло имя латинской точки, а не набранное.
    assert запросы[-1]["unit"] == "tbilisi-1"


def test_mcp_находки_точки_идут_через_общий_поиск(запросы: list[dict[str, Any]]) -> None:
    queries.findings_by_unit(reach=Reach("HQ", None, None), unit="Тбилиси-1", limit=10)

    assert запросы[-1]["unit"] == "tbilisi-1"


def test_незнакомое_имя_остаётся_как_набрано_и_выборка_пуста(
    запросы: list[dict[str, Any]],
) -> None:
    queries.list_inspections(reach=Reach("HQ", None, None), unit="Лондон-9")

    assert запросы[-1]["unit"] == "лондон-9"


# Каждый список справочника прячет снятые точки. Статическая проверка — на то, что новый список
# без фильтра не появится молча: она ищет в исходниках запросы `from units` без фильтра.
_СПИСКИ = {
    "directory._SELECT_UNITS_SQL": directory._SELECT_UNITS_SQL,
    "queries._UNITS_TOTAL_SQL": queries._UNITS_TOTAL_SQL,
    "queries._COUNTRY_SUMMARY_SQL": queries._COUNTRY_SUMMARY_SQL,
    "queries._UNIT_GEOGRAPHY_SQL": queries._UNIT_GEOGRAPHY_SQL,
    "queries._UNIT_IDS_SQL": queries._UNIT_IDS_SQL,
    "queries._UNIT_LAST_INSPECTIONS_SQL": queries._UNIT_LAST_INSPECTIONS_SQL,
    "prescriptions._UNIT_CHOICES_SQL": prescriptions._UNIT_CHOICES_SQL,
}


@pytest.mark.parametrize("имя", sorted(_СПИСКИ))
def test_список_справочника_прячет_снятые_точки(имя: str) -> None:
    assert ФИЛЬТР in _СПИСКИ[имя]


def test_ни_один_список_units_в_src_не_пропущен() -> None:
    """Запрос `from units` без join с проверками — список; в нём обязан быть фильтр."""
    корень = Path(__file__).resolve().parents[1] / "src"
    без_фильтра: list[str] = []
    for файл in корень.rglob("*.py"):
        текст = файл.read_text(encoding="utf-8")
        for m in re.finditer(r'"""(.*?)"""', текст, flags=re.S):
            sql = m.group(1)
            # Список: читает `units` главной таблицей, а не по ссылке проверки.
            if re.search(r"\bfrom units u\b", sql) and "join inspections" not in sql:
                if ФИЛЬТР not in sql and "units u where u.id" not in sql:
                    без_фильтра.append(f"{файл.name}: {sql.strip()[:60]!r}")
    # Исключения названы: запись строки, чтение одной строки по id, поиск по имени и карточки.
    # Справочник для поиска (`_DIRECTORY_SQL`) читает и снятые — они ведут на живые.
    допустимо = ("select count(*) from units u", "select 1 from units u", "u.merged_into::text")
    лишние = [x for x in без_фильтра if not any(d in x for d in допустимо)]
    assert not лишние, лишние


def test_свод_пиццерий_и_ссылки_рейтингов_не_видят_снятых() -> None:
    import inspect

    assert ФИЛЬТР in inspect.getsource(unit_profiles.hq_units)
