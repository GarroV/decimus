"""T294: карта синонимов формулировок видна управляющей компании и правится ею.

До этой задачи выученное машиной (T285, D119) было видно только в базе:
неверный синоним нечем было ни посмотреть, ни убрать — слой снятия и правки
появился задачей T292, но двери к нему не было. Здесь эта дверь.

Проверяется то, где ошибка дорогая, — и ровно то, что нельзя проверить
чтением кода:

1. **Право.** Карта — документ управляющей компании, а не история партнёра:
   без права на методику её не открыть и не поправить.
2. **Граница арендаторов.** Арендатор приходит из токена и только оттуда;
   названный аргументом — отказ, а не фильтр.
3. **Необратимость называется своими словами.** Снятие не удаляет строку и не
   переписывает основание: повторное снятие — отказ, а не «сделано».
4. **Пусто — это ответ.** Карта без базы отвечает отказом с именем переменной,
   а не пустой картой, которую спросивший прочтёт как «ничего не выучено».

База здесь не нужна: слой `db.synonyms` подменяется, потому что проверяется
поведение инструмента, а не запросы (те — в `tests/test_db_synonyms_curation.py`).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

pytest.importorskip("psycopg")

import src.db.synonyms as synonyms_api
from src.db.errors import ConfigError as DbConfigError
from src.db.errors import SynonymError
from src.mcp.catalogue import KIND_CHECKLIST, TOOLS
from src.mcp.checklist import Store
from src.mcp.rpc import handle

АРЕНДАТОР = "укашка"
ЧУЖОЙ = "партнёр-б"

#: Формулировка аудитора, а не пункт методики: в карте лежит сказанное живым
#: человеком, и именно его управляющая компания разбирает.
СКАЗАНО = "лужа у мойки"

#: Инструменты этой задачи — перебором по каталогу, а не списком имён: четвёртый,
#: написанный завтра, попадёт сюда сам. Ровно этого не хватило волне 3, где
#: забытый в таблице инструмент выпал из перебора молча.
КАРТА_СЛОВ = [spec for spec in TOOLS if spec.handler.__module__ == "src.mcp.phrases"]

#: Годные аргументы каждого: доводят до слоя базы, а не до разбора.
ГОДНЫЕ: dict[str, dict[str, Any]] = {
    "learned_phrases": {},
    "retract_learned_phrase": {"phrase": СКАЗАНО, "lang": "ru", "reason": "ведёт не туда"},
    "repoint_learned_phrase": {
        "phrase": СКАЗАНО,
        "lang": "ru",
        "item_code": "CLN01",
        "reason": "это про пол, а не про стену",
    },
}


def _строка(
    *,
    item_code: str = "CLN01",
    retracted_at: datetime | None = None,
    retraction_reason: str | None = None,
    corrected_at: datetime | None = None,
    correction_reason: str | None = None,
    previous_item_code: str | None = None,
    phrase: str = СКАЗАНО,
    lang: str = "ru",
    origin: str = synonyms_api.LEARNED,
) -> synonyms_api.PhraseAlias:
    return synonyms_api.PhraseAlias(
        item_code=item_code,
        lang=lang,
        phrase=phrase,
        key=synonyms_api.normalize_phrase(phrase),
        origin=origin,
        created_at=datetime(2026, 9, 10, 12, 0, 0),
        retracted_at=retracted_at,
        retraction_reason=retraction_reason,
        corrected_at=corrected_at,
        correction_reason=correction_reason,
        previous_item_code=previous_item_code,
    )


@pytest.fixture
def методика(tmp_path: Path) -> Store:
    """Хранилище версий: без него инструмент получил бы отказ ДОСТУПА, и тесты
    проверяли бы не то, ради чего написаны."""
    return Store(root=tmp_path / "хранилище", live=build_methodology(tmp_path / "живая"))


def _вызов(
    имя: str,
    аргументы: dict[str, Any],
    *,
    методика: Store | None,
    tenant: str = АРЕНДАТОР,
) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=tenant,
        checklist=методика,
        # Право на снятие ПРОВЕРКИ намеренно не выдано: карта синонимов —
        # документ методики, и открывается она правом методики. Выдай его
        # здесь, и тесты не заметили бы, что дверь перепутана.
        may_retract=False,
    )
    assert ответ is not None
    return ответ


def _текст(ответ: dict[str, Any]) -> str:
    результат = ответ.get("result")
    assert isinstance(результат, dict), ответ
    return str(результат["content"][0]["text"])


def _отказ(ответ: dict[str, Any]) -> str:
    результат = ответ["result"]
    assert результат.get("isError") is True, результат
    return _текст(ответ)


def _выдача(ответ: dict[str, Any]) -> dict[str, Any]:
    import json

    результат = ответ["result"]
    assert результат.get("isError") is not True, результат
    return dict(json.loads(_текст(ответ)))


# --- каталог: отдельное действие — отдельный инструмент (D125) -----------------


def test_просмотр_снятие_и_правка_объявлены_тремя_инструментами() -> None:
    """Отдельное действие — отдельный инструмент, а не флаг у соседнего (D125).

    Флаг `retract: true` у инструмента просмотра означал бы, что необратимое
    действие достигается опечаткой в аргументах читающего вызова.
    """
    имена = sorted(spec.name for spec in КАРТА_СЛОВ)

    assert имена == ["learned_phrases", "repoint_learned_phrase", "retract_learned_phrase"]
    for spec in КАРТА_СЛОВ:
        assert spec.kind == KIND_CHECKLIST, spec.name
        свойства = spec.input_schema["properties"]
        assert isinstance(свойства, dict)
        assert "tenant" not in свойства, spec.name
        assert "store" not in свойства, spec.name


def test_у_просмотра_нет_аргумента_который_правит() -> None:
    """Читающий инструмент не должен уметь править ничем — ни флагом, ни кодом."""
    просмотр = next(spec for spec in КАРТА_СЛОВ if spec.name == "learned_phrases")
    свойства = просмотр.input_schema["properties"]
    assert isinstance(свойства, dict)

    assert "reason" not in свойства
    assert "retract" not in свойства


# --- право: карта открывается правом методики ---------------------------------


@pytest.mark.parametrize("имя", sorted(ГОДНЫЕ))
def test_без_права_на_методику_карта_не_открывается(имя: str) -> None:
    """Карта синонимов — не история партнёра: в ней сырые слова аудиторов всех
    точек, и партнёрскому токену она не открывается вместе с его проверками."""
    отказ = _отказ(_вызов(имя, ГОДНЫЕ[имя], методика=None))

    assert "MCP_CHECKLIST_TENANTS" in отказ


# --- граница арендаторов ------------------------------------------------------


@pytest.fixture
def вызовы(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Подменённый слой карты, запоминающий, с чем его позвали.

    Подменяется `src.db.synonyms`: инструменты тянут его лениво, внутри
    функции, поэтому подмена в модуле доходит до вызова.
    """
    записано: list[dict[str, Any]] = []

    def список(**kwargs: Any) -> list[synonyms_api.PhraseAlias]:
        записано.append({"вызов": "list_phrases", **kwargs})
        return [_строка()]

    def снять(text: str, **kwargs: Any) -> synonyms_api.PhraseEdit:
        записано.append({"вызов": "retract_phrase", "text": text, **kwargs})
        return synonyms_api.PhraseEdit(
            synonyms_api.RETRACTED,
            _строка(
                retracted_at=datetime(2026, 9, 17, 9, 0, 0), retraction_reason=kwargs["reason"]
            ),
        )

    def переправить(text: str, **kwargs: Any) -> synonyms_api.PhraseEdit:
        записано.append({"вызов": "repoint_phrase", "text": text, **kwargs})
        return synonyms_api.PhraseEdit(
            synonyms_api.REPOINTED,
            _строка(
                item_code=kwargs["item_code"],
                corrected_at=datetime(2026, 9, 17, 9, 0, 0),
                correction_reason=kwargs["reason"],
                previous_item_code="CLN09",
            ),
        )

    monkeypatch.setattr(synonyms_api, "list_phrases", список)
    monkeypatch.setattr(synonyms_api, "retract_phrase", снять)
    monkeypatch.setattr(synonyms_api, "repoint_phrase", переправить)
    return записано


@pytest.mark.parametrize("имя", sorted(ГОДНЫЕ))
def test_арендатор_доезжает_до_слоя_из_токена(
    имя: str, методика: Store, вызовы: list[dict[str, Any]]
) -> None:
    """Код арендатора подставляет точка входа, разобрав токен, — и он доезжает
    до слоя. Снятый по дороге, он открыл бы карту всей сети."""
    _вызов(имя, ГОДНЫЕ[имя], методика=методика, tenant=ЧУЖОЙ)

    assert len(вызовы) == 1
    assert вызовы[0]["tenant"] == ЧУЖОЙ


@pytest.mark.parametrize("имя", sorted(ГОДНЫЕ))
def test_арендатор_названный_аргументом_получает_отказ(
    имя: str, методика: Store, вызовы: list[dict[str, Any]]
) -> None:
    """Аргумент `tenant` — не фильтр, а попытка назвать соседа: отказ, а не
    тихо отброшенное поле."""
    ответ = _вызов(имя, {**ГОДНЫЕ[имя], "tenant": "партнёр-а"}, методика=методика)

    assert "tenant" in str(ответ["error"]["message"])
    assert вызовы == []


# --- просмотр -----------------------------------------------------------------


def test_снятые_строки_по_умолчанию_не_показываются(
    методика: Store, вызовы: list[dict[str, Any]]
) -> None:
    """Умолчание то же, что у слоя: карта показывает работающее. Снятое видно по
    отдельной просьбе — иначе разбирать промахи не по чему."""
    _вызов("learned_phrases", {}, методика=методика)
    _вызов("learned_phrases", {"include_retracted": True}, методика=методика)

    assert вызовы[0]["include_retracted"] is False
    assert вызовы[1]["include_retracted"] is True


def test_снятая_строка_показана_снятой_а_не_обычной(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Снятая строка обязана отличаться в выдаче: иначе управляющая компания
    прочитает её как работающую и второй раз снимать не пойдёт."""
    monkeypatch.setattr(
        synonyms_api,
        "list_phrases",
        lambda **_: [
            _строка(
                retracted_at=datetime(2026, 9, 12, 8, 0, 0),
                retraction_reason="ведёт не туда",
            )
        ],
    )

    выдача = _вызов("learned_phrases", {"include_retracted": True}, методика=методика)
    строка = _выдача(выдача)["phrases"][0]

    assert строка["retracted_at"] == "2026-09-12T08:00:00"
    assert строка["retraction_reason"] == "ведёт не туда"


def test_пустая_карта_говорит_что_карта_пуста_а_не_молчит(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пусто — это ответ словами, а не пустой список, который агент перескажет
    как «такого не бывает»."""
    monkeypatch.setattr(synonyms_api, "list_phrases", lambda **_: [])

    выдача = _выдача(_вызов("learned_phrases", {}, методика=методика))

    assert выдача["phrases"] == []
    assert "no" in выдача["status"].lower()


def test_отбор_по_языку_не_выдаёт_опечатку_за_пустую_карту(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Спросили «sr», а карта на «ru» — ответ обязан назвать языки, которые в
    карте есть. Иначе опечатка в отборе читается как «ничего не выучено»."""

    def список(**kwargs: Any) -> list[synonyms_api.PhraseAlias]:
        if kwargs.get("lang"):
            return []
        return [_строка(lang="ru"), _строка(phrase="под ванной", lang="en")]

    monkeypatch.setattr(synonyms_api, "list_phrases", список)

    выдача = _выдача(_вызов("learned_phrases", {"lang": "sr"}, методика=методика))

    assert выдача["phrases"] == []
    assert выдача["languages_in_map"] == ["en", "ru"]


def test_предел_режет_показанное_но_не_врёт_про_счёт(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обрезанная выдача говорит об этом сама и называет полное число: иначе
    агент перескажет кусок карты как всю карту."""
    monkeypatch.setattr(
        synonyms_api,
        "list_phrases",
        lambda **_: [_строка(phrase=f"слово {номер}") for номер in range(5)],
    )

    выдача = _выдача(_вызов("learned_phrases", {"limit": 2}, методика=методика))

    assert len(выдача["phrases"]) == 2
    assert выдача["total"] == 5
    assert выдача["truncated"] is True


def test_предел_нулём_получает_отказ_а_не_пустую_выдачу(методика: Store) -> None:
    """Ноль прочитался бы как «в карте ничего нет»."""
    отказ = _отказ(_вызов("learned_phrases", {"limit": 0}, методика=методика))

    assert "limit" in отказ


# --- снятие -------------------------------------------------------------------


def test_снятие_говорит_что_строка_осталась_и_возвращается_только_человеком(
    методика: Store, вызовы: list[dict[str, Any]]
) -> None:
    """Снятие — пометка, а не удаление: ключ остаётся за строкой, поэтому ту же
    формулировку машина заново не выучит. Сказать это обязан сам ответ."""
    выдача = _выдача(
        _вызов("retract_learned_phrase", ГОДНЫЕ["retract_learned_phrase"], методика=методика)
    )

    assert вызовы[0]["вызов"] == "retract_phrase"
    assert вызовы[0]["text"] == СКАЗАНО
    assert вызовы[0]["reason"] == "ведёт не туда"
    assert выдача["retracted_at"] == "2026-09-17T09:00:00"
    assert "repoint_learned_phrase" in выдача["status"]


def test_повторное_снятие_не_выдаётся_за_сделанное(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вызывающий просил записать СВОЮ причину, а она не записывается: причина
    снятия не переписывается задним числом (тот же довод, что у снятия
    проверки). Ответ «готово» он однажды перескажет человеку как «принято»."""
    monkeypatch.setattr(
        synonyms_api,
        "retract_phrase",
        lambda *_, **__: synonyms_api.PhraseEdit(
            synonyms_api.ALREADY_RETRACTED,
            _строка(
                retracted_at=datetime(2026, 9, 12, 8, 0, 0),
                retraction_reason="сняли в прошлый вторник",
            ),
        ),
    )

    отказ = _отказ(
        _вызов("retract_learned_phrase", ГОДНЫЕ["retract_learned_phrase"], методика=методика)
    )

    assert "сняли в прошлый вторник" in отказ


def test_отказ_слоя_приходит_его_словами(методика: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ по существу написан слоем целиком, и пересказывать его здесь
    нельзя: второй экземпляр разошёлся бы с первым при первой же правке."""

    def отказать(*_: Any, **__: Any) -> None:
        raise SynonymError("Не названа причина снятия синонима")

    monkeypatch.setattr(synonyms_api, "retract_phrase", отказать)

    отказ = _отказ(
        _вызов(
            "retract_learned_phrase",
            {**ГОДНЫЕ["retract_learned_phrase"], "reason": " "},
            методика=методика,
        )
    )

    assert "причина" in отказ.lower()


def test_чужой_текст_наружу_не_уходит(методика: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """В сообщении драйвера базы бывает адрес, имя базы и путь к сокету. Ответ
    инструмента уходит в модель, то есть за пределы машины (T120)."""

    def упасть(*_: Any, **__: Any) -> None:
        беда = OSError("connection to server on socket /var/run/postgresql/.s.PGSQL.5432 failed")
        raise SynonymError(f"Синоним не снят (OperationalError): {беда}") from беда

    monkeypatch.setattr(synonyms_api, "retract_phrase", упасть)

    отказ = _отказ(
        _вызов("retract_learned_phrase", ГОДНЫЕ["retract_learned_phrase"], методика=методика)
    )

    assert "/var/run" not in отказ
    assert ".s.PGSQL" not in отказ
    assert "OSError" in отказ or "OperationalError" in отказ


# --- правка пункта ------------------------------------------------------------


def test_пункт_сверяется_с_методикой_до_похода_в_базу(
    методика: Store, вызовы: list[dict[str, Any]]
) -> None:
    """Синоним, переправленный на несуществующий код, тихо перестал бы работать:
    быстрый путь не нашёл бы пункта, а в карте строка выглядела бы исправленной."""
    отказ = _отказ(
        _вызов(
            "repoint_learned_phrase",
            {**ГОДНЫЕ["repoint_learned_phrase"], "item_code": "ZZZ99"},
            методика=методика,
        )
    )

    assert "ZZZ99" in отказ
    assert вызовы == [], "до базы дело дойти не должно было"


def test_правка_называет_куда_строка_вела_раньше(
    методика: Store, вызовы: list[dict[str, Any]]
) -> None:
    """Исправленный синоним обязан отличаться от изначально верного: иначе
    разбор промахов модели упирается в карту, где все строки правильные."""
    выдача = _выдача(
        _вызов("repoint_learned_phrase", ГОДНЫЕ["repoint_learned_phrase"], методика=методика)
    )

    assert выдача["item_code"] == "CLN01"
    assert выдача["previous_item_code"] == "CLN09"


def test_правка_на_тот_же_пункт_не_выдаётся_за_правку(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Строка и так ведёт туда: причина не записана, и «готово» было бы ложью."""
    monkeypatch.setattr(
        synonyms_api,
        "repoint_phrase",
        lambda *_, **__: synonyms_api.PhraseEdit(synonyms_api.ALREADY_POINTED, _строка()),
    )

    отказ = _отказ(
        _вызов("repoint_learned_phrase", ГОДНЫЕ["repoint_learned_phrase"], методика=методика)
    )

    assert "CLN01" in отказ


def test_возврат_снятой_строки_в_работу_назван_словами(
    методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Снятая строка возвращается в работу этим же вызовом — и это событие, а не
    оттенок: человек обязан прочитать, что формулировка снова работает."""
    monkeypatch.setattr(
        synonyms_api,
        "repoint_phrase",
        lambda *_, **__: synonyms_api.PhraseEdit(
            synonyms_api.RESTORED,
            _строка(
                item_code="CLN01",
                corrected_at=datetime(2026, 9, 17, 9, 0, 0),
                correction_reason="сняли по ошибке",
                previous_item_code="CLN09",
            ),
        ),
    )

    выдача = _выдача(
        _вызов("repoint_learned_phrase", ГОДНЫЕ["repoint_learned_phrase"], методика=методика)
    )

    assert выдача["outcome"] == synonyms_api.RESTORED
    assert "back in work" in выдача["status"]


# --- стенд без базы -----------------------------------------------------------


@pytest.mark.parametrize("имя", sorted(ГОДНЫЕ))
def test_без_базы_карта_отвечает_отказом_а_не_пустотой(
    имя: str, методика: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Карты нет» и «карта пуста» — разные ответы. Отказ называет переменную,
    иначе человек пойдёт искать поломку, которой нет."""

    def без_базы(*_: Any, **__: Any) -> None:
        raise DbConfigError("не задана DATABASE_URL")

    monkeypatch.setattr(synonyms_api, "list_phrases", без_базы)
    monkeypatch.setattr(synonyms_api, "retract_phrase", без_базы)
    monkeypatch.setattr(synonyms_api, "repoint_phrase", без_базы)

    отказ = _отказ(_вызов(имя, ГОДНЫЕ[имя], методика=методика))

    переменная = "DATABASE_URL" if имя == "learned_phrases" else "DATABASE_RETRACTION_URL"
    assert переменная in отказ
    assert "ConfigError" not in отказ
