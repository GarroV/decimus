"""Синоним формулировки в разговоре: когда копится и когда срабатывает (T285).

Решение владельца D119: прямого совпадения с методикой не нашлось, а запись всё
равно появилась — сказанное складывается синонимом пункта и работает при
следующем поиске; прямое совпадение синонима второй строки не заводит.

Три свойства, ради которых решение и принималось, заперты здесь со стороны
самого разговора, а не слоя доступа: **копится** непрямое попадание,
**не копится** прямое, и **срабатывает** накопленное — без модели и без
повторного вопроса тому же человеку о том же самом.

Карта синонимов живёт в Postgres (T284), но эти тесты идут без базы намеренно:
проверяется поведение бота, а не SQL, и связывать разговор с поднятой базой
значило бы прогонять его только там, где она есть.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    Calls,
    callback_query,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
)

from src.bot import view
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import fixed_keyboard
from src.bot.phrases import synonyms
from src.bot.refusal import item_title
from src.db.synonyms import LEARNED, REMEMBERED, PhraseAlias, PhraseMemory
from src.domain import get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Пункт синтетической методики с ОДНОЙ зоной и одним классом: накопленный
#: синоним применяется сразу, спрашивать нечего.
ОДНОЗОННЫЙ = "CLN05"
#: Пункт многих зон — его кандидатом отвечает модель, и зону она называет сама.
МНОГОЗОННЫЙ = "PRD06"
#: Слова, которых карта кадров не знает: прямого совпадения не будет.
НЕПРЯМЫЕ_СЛОВА = "духовка закоптилась, глянь"
ЯЗЫК_РЕЧИ = "ru"


def начата(lang: str = "ru") -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", lang, date="2026-08-21", auditor="Гарро")


def карта_молчит(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Карта синонимов пуста — и запоминает всё, о чём её просят."""
    return _карта(monkeypatch, None)


def _карта(monkeypatch: pytest.MonkeyPatch, alias: PhraseAlias | None) -> Calls:
    записано = Calls()

    def _lookup(text: str, **kw: Any) -> PhraseAlias | None:
        return alias

    def _remember(text: str, **kw: Any) -> PhraseMemory:
        записано.append((text, kw.get("item_code"), kw.get("lang"), kw.get("origin")))
        return PhraseMemory(
            REMEMBERED,
            PhraseAlias(
                item_code=str(kw.get("item_code")),
                lang=str(kw.get("lang")),
                phrase=text,
                key=synonyms.normalize_phrase(text),
                origin=str(kw.get("origin")),
                created_at=None,  # type: ignore[arg-type]
            ),
        )

    monkeypatch.setattr(synonyms, "lookup_phrase", _lookup)
    monkeypatch.setattr(synonyms, "remember_phrase", _remember)
    return записано


def карта_знает(monkeypatch: pytest.MonkeyPatch, code: str, phrase: str) -> Calls:
    return _карта(
        monkeypatch,
        PhraseAlias(
            item_code=code,
            lang=ЯЗЫК_РЕЧИ,
            phrase=phrase,
            key=synonyms.normalize_phrase(phrase),
            origin=LEARNED,
            created_at=None,  # type: ignore[arg-type]
        ),
    )


async def test_непрямое_совпадение_ложится_синонимом(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сказано иначе, пункт выбрал человек — система обязана это запомнить.

    Ровно то, чего требует D119: переспрашивать одно и то же каждый раз нельзя.
    Происхождение записи — машинное (`learned`), потому что свёл формулировку с
    пунктом разбор, а не рука управляющей компании.
    """
    начата()
    записано = карта_молчит(monkeypatch)
    stub_classify(monkeypatch, suggestion(candidate(МНОГОЗОННЫЙ, "D1", "hot_kitchen", "Тара")))
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась"
    assert записано == [(НЕПРЯМЫЕ_СЛОВА, МНОГОЗОННЫЙ, ЯЗЫК_РЕЧИ, LEARNED)]


async def test_прямое_совпадение_синонима_не_заводит(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вторая половина решения, и без неё карта распухла бы своими же словами.

    Сверка со списком нарушений нашла пункт сама — записывать в карту нечего:
    эта формулировка и есть прямое совпадение.
    """
    начата()
    записано = карта_молчит(monkeypatch)
    звонки = stub_classify(monkeypatch, suggestion())
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption="грязная печь", message_id=601))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "быстрый путь не сделал записи"
    assert звонки == [], "прямое совпадение ушло в модель"
    assert записано == [], "прямое совпадение завело синоним"


async def test_известная_формулировка_пишет_запись_без_модели(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ради этого решение и принималось: во второй раз то же слово уже знают.

    Модель не зовётся вовсе, вопроса аудитору не задаётся, а под записью стоит
    выход к модели — тот же, что у записи по словам: подтверждения не было, и
    чинить промах иначе было бы нечем.
    """
    начата()
    карта_знает(monkeypatch, ОДНОЗОННЫЙ, НЕПРЯМЫЕ_СЛОВА)
    звонки = stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "накопленный синоним не сработал"
    запись = состояние.findings[0]
    assert (запись.code, запись.zone) == (ОДНОЗОННЫЙ, "hot_kitchen")
    assert запись.text == НЕПРЯМЫЕ_СЛОВА, "в отчёт ушли не слова аудитора"
    assert звонки == [], "карта знала пункт, а материал всё равно ушёл в модель"
    assert session.last_text == view.learned_block(
        запись,
        "ru",
        title=item_title(запись.code, "ru", chat_id=CHAT_ID),
        chat_id=CHAT_ID,
        zone_from_item=True,
    ), "запись по накопленному синониму показана чужим блоком"
    assert session.keyboard_data() == [
        b.callback_data for row in fixed_keyboard(запись.n, "ru").inline_keyboard for b in row
    ], "выхода к модели под записью без подтверждения нет"


async def test_накопленное_второй_строки_не_заводит(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сработавший синоним — это и есть прямое совпадение, писать его незачем."""
    начата()
    записано = карта_знает(monkeypatch, ОДНОЗОННЫЙ, НЕПРЯМЫЕ_СЛОВА)
    stub_classify(monkeypatch, suggestion())
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, photo_message("frame-1", caption=НЕПРЯМЫЕ_СЛОВА, message_id=601))

    assert записано == [], "сработавший синоним лёг в карту второй строкой"
