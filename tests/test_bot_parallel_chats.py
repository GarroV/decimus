"""Разные чаты обрабатываются параллельно, один чат — по порядку (GHSA-7gm6-hc9m-w3vc).

Опрос идёт настоящим `run_polling` и настоящим `Dispatcher.start_polling`:
обновления приходят в ответе на `getUpdates`, а не отдаются в `feed_update`
по одному. Только так видно, как диспетчер берёт обновления в работу —
`feed_update` сам по себе параллельности не знает.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from itertools import count
from typing import Any

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.methods import GetMe, GetUpdates, TelegramMethod
from aiogram.types import Chat, Message, Update, User
from bot_harness import RecordingSession

from src.bot.app import build_dispatcher, run_polling
from src.bot.config import BotSettings
from src.bot.serial import ChatSerialMiddleware

pytestmark = pytest.mark.asyncio

WAIT = 3.0
_ids = count(1)


class PollingSession(RecordingSession):
    """Сессия, у которой `getUpdates` отдаёт заготовленные обновления ровно раз."""

    def __init__(self, updates: list[Update]) -> None:
        super().__init__()
        self._updates = updates

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> Any:
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="bot", username="bot")
        if isinstance(method, GetUpdates):
            batch, self._updates = self._updates, []
            if not batch:
                await asyncio.sleep(3600)
            return batch
        return await super().make_request(bot, method, timeout)


def update(chat_id: int, text: str) -> Update:
    return Update(
        update_id=next(_ids),
        message=Message(
            message_id=next(_ids),
            date=datetime.now(tz=timezone.utc),
            chat=Chat(id=chat_id, type="private"),
            from_user=User(id=chat_id, is_bot=False, first_name="a"),
            text=text,
        ),
    )


async def poll(dispatcher: Dispatcher, updates: list[Update], until: asyncio.Event) -> None:
    """Опрашивать, пока `until` не взведён, и остановиться."""
    bot = Bot(token="123456:test-token-not-real", session=PollingSession(updates))
    task = asyncio.create_task(run_polling(dispatcher, bot))
    try:
        await asyncio.wait_for(until.wait(), WAIT)
    finally:
        await dispatcher.stop_polling()
        await asyncio.wait_for(task, WAIT)


def dispatcher_with(handler: Any, limit: int = 16) -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.update.outer_middleware(ChatSerialMiddleware(limit))
    router = Router()
    router.message()(handler)
    dispatcher.include_router(router)
    return dispatcher


async def test_slow_chat_does_not_hold_other_chats() -> None:
    release = asyncio.Event()
    fast_done = asyncio.Event()

    async def handler(message: Message) -> None:
        if message.chat.id == 1:
            await release.wait()
        else:
            fast_done.set()

    dispatcher = dispatcher_with(handler)
    updates = [update(1, "slow"), update(2, "fast")]
    bot = Bot(token="123456:test-token-not-real", session=PollingSession(updates))
    task = asyncio.create_task(run_polling(dispatcher, bot))
    try:
        await asyncio.wait_for(fast_done.wait(), WAIT)
    finally:
        release.set()
        await dispatcher.stop_polling()
        await asyncio.wait_for(task, WAIT)


async def test_one_chat_is_handled_in_order() -> None:
    log: list[str] = []
    done = asyncio.Event()

    async def handler(message: Message) -> None:
        log.append(f"start {message.text}")
        if message.text == "first":
            await asyncio.sleep(0.2)
        log.append(f"end {message.text}")
        if message.text == "third":
            done.set()

    dispatcher = dispatcher_with(handler)
    await poll(dispatcher, [update(1, "first"), update(1, "second"), update(1, "third")], done)

    assert log == [
        "start first", "end first",
        "start second", "end second",
        "start third", "end third",
    ]  # fmt: skip


async def test_limit_caps_concurrent_updates() -> None:
    running = 0
    peak = 0
    finished = 0
    done = asyncio.Event()

    async def handler(message: Message) -> None:
        nonlocal running, peak, finished
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        finished += 1
        if finished == 4:
            done.set()

    dispatcher = dispatcher_with(handler, limit=2)
    await poll(dispatcher, [update(chat, "x") for chat in (1, 2, 3, 4)], done)

    assert peak == 2


async def test_build_dispatcher_serializes_chats() -> None:
    dispatcher = build_dispatcher(BotSettings(token="unused-in-tests", mode="polling"))

    assert any(isinstance(m, ChatSerialMiddleware) for m in dispatcher.update.outer_middleware)
