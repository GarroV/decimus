"""#359: аудитор отмечает повтор кнопкой, а не только из командной строки.

Правило D191 («повтор стоит вдвое») работало в движке, но обход идёт в чате: до
этой кнопки отметить повтор на точке было нечем, и правило существовало только
для папочных проверок.

Кнопка переключает пометку в обе стороны. Ошибиться в ней — то же, что
ошибиться в классе нарушения: цена записи меняется вдвое, и снимать пометку
обязано быть так же просто, как ставить.
"""

from __future__ import annotations

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot

from src import domain
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings

pytestmark = [pytest.mark.asyncio]

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


def запись():
    состояние = domain.get_state(CHAT_ID)
    assert состояние is not None
    найдена = состояние.finding(1)
    assert найдена is not None
    return найдена


async def начата() -> None:
    domain.start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    domain.add_finding(CHAT_ID, "PRD01", "D1", "fridge", "текст")


async def test_кнопка_ставит_пометку_повтора(domain_env: object) -> None:
    await начата()
    bot, _session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, callback_query("edit:1:repeat"))

    assert запись().repeat is True


async def test_кнопка_снимает_пометку(domain_env: object) -> None:
    await начата()
    domain.edit_finding(CHAT_ID, 1, repeat=True)
    bot, _session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, callback_query("edit:1:repeat"))

    assert запись().repeat is False


async def test_пометка_меняет_цену_записи(domain_env: object) -> None:
    # Проверяется наблюдаемый результат, а не факт записи в файл: пометка
    # существует ради цены, и если оценка не сдвинулась — она ничего не значит.
    await начата()
    было = domain.score(CHAT_ID).pct
    bot, _session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, callback_query("edit:1:repeat"))

    assert domain.score(CHAT_ID).pct < было, "пометка не отразилась на оценке"


async def test_аудитору_сказано_что_изменилось(domain_env: object) -> None:
    # Молчаливое переключение цены — худший вид кнопки: аудитор не знает, в
    # каком состоянии запись, и отметит её дважды.
    await начата()
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, callback_query("edit:1:repeat"))

    assert session.last_text, "бот промолчал о переключении пометки"
    assert "овтор" in session.last_text
