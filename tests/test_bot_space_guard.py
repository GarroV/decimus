"""Review Focus 6: апдейт по проверке чужого пространства до обработчика не доходит."""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import TelegramObject
from bot_harness import RecordingSession, callback_query, make_bot, text_message

from src.bot.access import SPACE_KEY, ChatSpaceMiddleware

pytestmark = pytest.mark.asyncio


async def _прогнать(
    event: TelegramObject, *, space: str, чья: str | None
) -> tuple[list[TelegramObject], RecordingSession]:
    bot, session = make_bot()
    дошло: list[TelegramObject] = []

    async def handler(e: TelegramObject, _data: dict[str, Any]) -> None:
        дошло.append(e)

    guard = ChatSpaceMiddleware(read_tenant=lambda _chat: чья)
    await guard(handler, event.as_(bot), {SPACE_KEY: space})
    return дошло, session


async def test_своя_проверка_проходит() -> None:
    дошло, _ = await _прогнать(text_message("фото"), space="GE", чья="GE")
    assert дошло


async def test_чата_без_проверки_заслон_не_касается() -> None:
    дошло, _ = await _прогнать(text_message("/start"), space="GE", чья=None)
    assert дошло


async def test_старая_кнопка_по_чужой_проверке_не_доходит() -> None:
    дошло, session = await _прогнать(callback_query("zone:3"), space="GE", чья="HQ")
    assert дошло == []
    ответы = [c for c in session.calls if isinstance(c, AnswerCallbackQuery)]
    assert len(ответы) == 1 and ответы[0].show_alert is True


async def test_сообщение_в_чужую_проверку_не_доходит() -> None:
    дошло, session = await _прогнать(text_message("холодильник грязный"), space="HQ", чья="GE")
    assert дошло == []
    assert len([c for c in session.calls if isinstance(c, SendMessage)]) == 1


async def test_старый_код_тенанта_в_проверке_считается_уК() -> None:
    дошло, _ = await _прогнать(text_message("фото"), space="HQ", чья="default")
    assert дошло
