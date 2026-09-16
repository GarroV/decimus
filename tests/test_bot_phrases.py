"""Карта синонимов формулировок со стороны разговора (T285, решение D119).

Решение владельца: прямого совпадения с методикой не нашлось, а запись всё-таки
появилась — сказанное складывается синонимом пункта и работает при следующем
поиске; прямое совпадение синонима второй строки не заводит.

Хранилище и слой доступа к нему — блок `db` (T284). Здесь проверяется ровно то,
что добавляет этот блок: **когда** карту спрашивают, **когда** в неё пишут и,
главное, чего НЕ делает отказ карты. Невыученное слово не повод сказать
аудитору, что проверка не сохранена: обход на точке важнее любой памяти
(`src.bot.roster`, тот же довод).

Слой отдаёт КОД пункта, а не пункт: действует ли код в издании ТОЙ проверки,
решает этот блок — синоним, оставшийся от снятого пункта, никуда не приводит.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from bot_harness import CHAT_ID

from src.bot.phrases import learn, recall
from src.db import synonyms
from src.db.errors import ConfigError, SynonymError
from src.db.synonyms import ALREADY_KNOWN, CONFLICT, LEARNED, REMEMBERED, PhraseAlias, PhraseMemory
from src.domain import start_inspection

#: Пункт синтетической методики с одной зоной и одним классом: применить такой
#: синоним можно сразу, ничего не спрашивая.
ПУНКТ = "CLN05"
#: Служебный пункт — его ставит только аудитор вручную, разбор его не предлагает.
СЛУЖЕБНЫЙ = "MGM22"
#: Сводная строка процесса: не нарушение, записью не бывает.
СВОДНАЯ = "PRD16"
СЛОВА = "духовка вся закоптилась"
ЯЗЫК = "ru"


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", ЯЗЫК, date="2026-08-21", auditor="Гарро")


def строка(code: str = ПУНКТ, phrase: str = СЛОВА, origin: str = LEARNED) -> PhraseAlias:
    return PhraseAlias(
        item_code=code,
        lang=ЯЗЫК,
        phrase=phrase,
        key=synonyms.normalize_phrase(phrase),
        origin=origin,
        created_at=None,  # type: ignore[arg-type]
    )


def карта_знает(monkeypatch: pytest.MonkeyPatch, alias: PhraseAlias | None) -> list[dict[str, Any]]:
    """Подменить чтение карты и вернуть список заданных ей вопросов."""
    спрошено: list[dict[str, Any]] = []

    def _lookup(text: str, *, lang: str, tenant: str = synonyms.DEFAULT_TENANT) -> Any:
        спрошено.append({"text": text, "lang": lang, "tenant": tenant})
        return alias

    monkeypatch.setattr(synonyms, "lookup_phrase", _lookup)
    return спрошено


def карта_принимает(
    monkeypatch: pytest.MonkeyPatch, outcome: str = REMEMBERED
) -> list[dict[str, Any]]:
    """Подменить запись в карту и вернуть список сделанных в неё записей."""
    записано: list[dict[str, Any]] = []

    def _remember(
        text: str,
        *,
        item_code: str,
        lang: str,
        origin: str = LEARNED,
        tenant: str = synonyms.DEFAULT_TENANT,
    ) -> PhraseMemory:
        записано.append(
            {"text": text, "item_code": item_code, "lang": lang, "origin": origin, "tenant": tenant}
        )
        return PhraseMemory(outcome, строка(item_code, text, origin))

    monkeypatch.setattr(synonyms, "remember_phrase", _remember)
    return записано


def карта_отказывает(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise exc

    monkeypatch.setattr(synonyms, "lookup_phrase", _fail)
    monkeypatch.setattr(synonyms, "remember_phrase", _fail)


# --- что карта поднимает -------------------------------------------------------


def test_известная_формулировка_поднимает_пункт(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ради этого решение и принято: во второй раз то же слово уже знают."""
    начата()
    спрошено = карта_знает(monkeypatch, строка())

    поднято = recall(СЛОВА, lang=ЯЗЫК, chat_id=CHAT_ID)

    assert поднято is not None and поднято.code == ПУНКТ
    assert поднято.phrase == СЛОВА, "показать аудитору нечего — забыта сама формулировка"
    assert спрошено == [{"text": СЛОВА, "lang": ЯЗЫК, "tenant": synonyms.DEFAULT_TENANT}]


def test_незнакомая_формулировка_молчит(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустая карта — обычный ответ «не знаю», а не отказ."""
    начата()
    карта_знает(monkeypatch, None)

    assert recall(СЛОВА, lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_пустые_слова_в_карту_не_ходят(domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Голый кадр без слов спрашивать не о чем — и ходить за этим в базу тоже."""
    начата()
    спрошено = карта_знает(monkeypatch, строка())

    assert recall("   ", lang=ЯЗЫК, chat_id=CHAT_ID) is None
    assert спрошено == [], "поход в базу за пустой строкой"


def test_синоним_снятого_пункта_никуда_не_приводит(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Код проверяется по изданию ТОЙ проверки — это сказано в контракте слоя.

    Методика у каждой проверки своя (D063, D064), и пункт из неё могли снять.
    Синоним, который на него показывает, обязан замолчать, а не уронить разбор.
    """
    начата()
    карта_знает(monkeypatch, строка("НЕТ-ТАКОГО"))

    with caplog.at_level(logging.WARNING):
        assert recall(СЛОВА, lang=ЯЗЫК, chat_id=CHAT_ID) is None
    assert "НЕТ-ТАКОГО" in caplog.text, "молчание без следа — разбирать будет нечего"


@pytest.mark.parametrize("code", [СЛУЖЕБНЫЙ, СВОДНАЯ])
def test_непредлагаемый_пункт_синонимом_не_применяется(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """Разбор таких пунктов не предлагает (`fastpath._offered`) — и карта не вправе.

    Служебный пункт ставит только сам аудитор, сводная строка процесса записью
    не бывает вовсе. Подставить их без подтверждения значило бы обойти правило
    с другой стороны.
    """
    начата()
    карта_знает(monkeypatch, строка(code))

    assert recall(СЛОВА, lang=ЯЗЫК, chat_id=CHAT_ID) is None


def test_отказ_карты_разбор_не_роняет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """База недоступна — система просто не помнит, а проверка идёт дальше."""
    начата()
    карта_отказывает(monkeypatch, SynonymError("карта недоступна"))

    with caplog.at_level(logging.WARNING):
        assert recall(СЛОВА, lang=ЯЗЫК, chat_id=CHAT_ID) is None
    assert caplog.records, "отказ карты проглочен молча"


def test_ненастроенная_база_разбор_не_роняет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`DATABASE_URL` не задан — бот поднимается и работает (`src.bot.roster`).

    Отказ приходит не `SynonymError`, а `ConfigError` — он старше и летит из
    проверки окружения. Ловить в этом месте надо блок целиком.
    """
    начата()
    карта_отказывает(monkeypatch, ConfigError("нет DATABASE_URL"))

    assert recall(СЛОВА, lang=ЯЗЫК, chat_id=CHAT_ID) is None


# --- что в карту ложится -------------------------------------------------------


def test_разобранная_формулировка_ложится_синонимом(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D119: непрямое совпадение копится — происхождением машинным, не ручным."""
    начата()
    записано = карта_принимает(monkeypatch)

    assert learn(СЛОВА, item_code=ПУНКТ, lang=ЯЗЫК, chat_id=CHAT_ID) == REMEMBERED
    assert записано == [
        {
            "text": СЛОВА,
            "item_code": ПУНКТ,
            "lang": ЯЗЫК,
            "origin": LEARNED,
            "tenant": synonyms.DEFAULT_TENANT,
        }
    ]


def test_известный_синоним_второй_строки_не_заводит(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Исход называется кодом, и он же — ответ на «заводить ли ещё раз»."""
    начата()
    карта_принимает(monkeypatch, ALREADY_KNOWN)

    assert learn(СЛОВА, item_code=ПУНКТ, lang=ЯЗЫК, chat_id=CHAT_ID) == ALREADY_KNOWN


def test_разночтение_называется_в_журнале(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Та же формулировка уже ведёт к другому пункту — строка не переписана.

    Переписать её нечем и намеренно: прав UPDATE у роли приложения нет (T284).
    Значит, единственное, что здесь можно сделать честно, — сказать вслух, а
    снятие неверной строки остаётся задачей управляющей компании (#255).
    """
    начата()
    карта_принимает(monkeypatch, CONFLICT)

    with caplog.at_level(logging.WARNING):
        assert learn(СЛОВА, item_code=ПУНКТ, lang=ЯЗЫК, chat_id=CHAT_ID) == CONFLICT
    assert caplog.records, "разночтение проглочено молча"


def test_пустая_формулировка_синонимом_не_становится(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Кадр без слов покрывать синонимом нечего — покрывать нечего и в карте."""
    начата()
    записано = карта_принимает(monkeypatch)

    assert learn("  ", item_code=ПУНКТ, lang=ЯЗЫК, chat_id=CHAT_ID) == ""
    assert записано == []


@pytest.mark.parametrize("code", [СЛУЖЕБНЫЙ, СВОДНАЯ, "НЕТ-ТАКОГО"])
def test_мёртвая_строка_в_карту_не_ложится(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """Синоним, который применить нельзя, — мусор в карте управляющей компании.

    Проверка та же, что на чтении, и стоит она по обе стороны намеренно: карту
    читает и человек, разбирая промахи, а строка, которая никогда не сработает,
    ему врёт о том, чему система научилась.
    """
    начата()
    записано = карта_принимает(monkeypatch)

    assert learn(СЛОВА, item_code=code, lang=ЯЗЫК, chat_id=CHAT_ID) == ""
    assert записано == []


def test_отказ_записи_проверку_не_роняет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Главное свойство всего этого файла: запись уже легла, и она важнее памяти."""
    начата()
    карта_отказывает(monkeypatch, SynonymError("карта не приняла"))

    with caplog.at_level(logging.WARNING):
        assert learn(СЛОВА, item_code=ПУНКТ, lang=ЯЗЫК, chat_id=CHAT_ID) == ""
    assert caplog.records, "отказ карты проглочен молча"
