"""Зона следует из пункта, когда её не называл человек (задача #218).

Живой прогон 07.09.2026: аудитор сказал про печь, а запись легла в холодный цех.
Разбор показал, что классификатор выбрал пункт ВЕРНО, а зону подставила система:
модель на вопрос без подсказки отвечает «места не знаю» (`UNKNOWN`), и на это
место подставлялась зона ПРОШЛОЙ записи.

Данные при этом знают правильный ответ. Пункт про печь методика держит только в
горячем цехе — таких пунктов 59 из 136 (замер того же дня). Значит там, где зону
не называл человек, её незачем угадывать: у пункта она одна.

Где угадывать всё-таки нечем — у пункта зон несколько, — поведение остаётся
прежним: подставляется прошлая зона с оговоркой о догадке. Эту половину стерегут
тесты `test_bot_zone_guess_on_model_path.py`, и ослаблять их задача не имеет
права.

**Слово человека сильнее.** Названную зону система не подменяет никогда, даже
если пункт её не держит: правило 6 методики отдаёт зону аудитору, а движок о
нетипичной зоне предупреждает сам.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    callback_query,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
)

from src.bot import sidecar
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.domain import get_state, only_zone, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


def начата() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru", date="2026-08-21", auditor="Гарро")


async def разобрать(
    dp: Any, bot: Any, monkeypatch: pytest.MonkeyPatch, *, код: str, зона: str, слова: str
) -> None:
    """Кадр с комментарием → ответ модели → аудитор подтверждает кандидата."""
    stub_classify(monkeypatch, suggestion(candidate(код, "D1", зона, "Нагар на поду печи")))
    await feed(dp, bot, photo_message("frame-1", caption=слова, message_id=601))
    await feed(dp, bot, callback_query("rec:pick:0"))


# --- то, что знает сама методика ----------------------------------------------


def test_единственная_зона_пункта_известна(domain_env: Path) -> None:
    """Печь методика держит в одной зоне — это и есть ответ, а не догадка."""
    assert only_zone("CLN05", chat_id=CHAT_ID) == "hot_kitchen"


def test_пункт_многих_зон_единственной_не_имеет(domain_env: Path) -> None:
    """Где зон несколько, выводить нечего — и выдумывать нельзя."""
    assert only_zone("CLN03", chat_id=CHAT_ID) is None


def test_незнакомый_пункт_зоны_не_даёт(domain_env: Path) -> None:
    """Отсутствие пункта — не повод падать в разговоре с аудитором."""
    assert only_zone("НЕТ-ТАКОГО", chat_id=CHAT_ID) is None


# --- поведение в разговоре -----------------------------------------------------


async def test_печь_без_названной_зоны_ложится_в_свою_зону(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сам дефект живого прогона: память о прошлой записи уводила печь в чужой цех."""
    начата()
    sidecar.remember_zone(CHAT_ID, "cold_kitchen")
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await разобрать(dp, bot, monkeypatch, код="CLN05", зона="cold_kitchen", слова="грязная печь")

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings, "запись не появилась"
    assert состояние.findings[0].zone == "hot_kitchen"


async def test_пункт_многих_зон_прошлую_зону_сохраняет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Выводить зону не из чего — прежнее поведение с оговоркой остаётся."""
    начата()
    sidecar.remember_zone(CHAT_ID, "cold_kitchen")
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await разобрать(dp, bot, monkeypatch, код="CLN03", зона="cold_kitchen", слова="грязно")

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings
    assert состояние.findings[0].zone == "cold_kitchen"


async def test_названную_человеком_зону_система_не_подменяет(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правило 6: зону определяет аудитор. Сказал «в холодном цеху» — так и пишем.

    Движок о нетипичной для пункта зоне предупредит сам, и это его дело, а не
    повод переписать сказанное человеком.
    """
    начата()
    bot, _ = make_bot()
    dp = build_dispatcher(SETTINGS)

    await разобрать(
        dp,
        bot,
        monkeypatch,
        код="CLN05",
        зона="cold_kitchen",
        слова="в холодном цеху грязная печь",
    )

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.findings
    assert состояние.findings[0].zone == "cold_kitchen"
