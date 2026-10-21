"""Параллельные чаты и очередь внутри чата (F-122, #1006).

Бот обрабатывает обновления задачами: медленная голосовая или тормозящий
провайдер одного чата не должны держать ответы остальным. Порядок внутри чата
при этом обязан остаться (T059): его держит замок чата (`src/bot/chat_lock.py`).

Три вещи, и каждая проверяется через настоящий диспетчер:

* обновления одного чата не наезжают друг на друга и идут в порядке прихода —
  без замка медленный разбор первого пропустил бы второй вперёд;
* разные чаты идут параллельно — через настоящий `start_polling` с теми же
  настройками, что у бота (`app.POLLING_OPTIONS`): с `handle_as_tasks=False`
  чат Б ждал бы чата А;
* записи в реестре замков не копятся: после работы он пуст.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.methods import GetMe, GetUpdates
from aiogram.types import Update, User
from bot_harness import RecordingSession, photo_message, text_message

from src.bot import app
from src.bot.chat_lock import ChatLockMiddleware, ChatLocks
from src.bot.config import BotSettings
from src.bot.material import Material
from src.domain import start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", mode="polling")
CHAT_A = 4242
CHAT_B = 5353
#: Сколько «разбирается» материал. Достаточно, чтобы чужое обновление успело
#: вклиниться, если ему не мешает замок, и мало, чтобы не тянуть прогон.
SLOW_SEC = 0.15


class SlowParse:
    """Разбор материала с задержкой: по журналу видно, кто с кем перекрылся."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []

    async def __call__(self, message: object, material: Material, lang: str) -> None:
        file_id = material.photo_file_ids[0]
        self.log.append(("enter", file_id))
        await asyncio.sleep(SLOW_SEC)
        self.log.append(("exit", file_id))


class PollingSession(RecordingSession):
    """Сессия, которая один раз отдаёт заготовленные обновления, потом молчит."""

    def __init__(self, batch: list[Update]) -> None:
        super().__init__()
        self._batch = batch

    async def make_request(self, bot: Bot, method: Any, timeout: int | None = None) -> Any:  # noqa: ASYNC109
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="bot", username="decimus_test_bot")
        if isinstance(method, GetUpdates):
            batch, self._batch = self._batch, []
            if not batch:
                await asyncio.sleep(0.05)
            return batch
        return await super().make_request(bot, method, timeout)


def captioned(file_id: str, chat_id: int) -> Update:
    message = photo_message(file_id, caption=f"подпись {file_id}", chat_id=chat_id)
    return Update(update_id=abs(hash(file_id)) % 10**6, message=message)


async def run_polling(updates: list[Update], parse: SlowParse, *, settle: float) -> None:
    session = PollingSession(updates)
    bot = Bot(token="111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    dp = app.build_dispatcher(SETTINGS, on_material=parse, album_window=5.0)
    task = asyncio.create_task(
        dp.start_polling(bot, handle_signals=False, close_bot_session=False, **app.POLLING_OPTIONS)
    )
    await asyncio.sleep(settle)
    await dp.stop_polling()
    await task


async def test_updates_of_one_chat_do_not_overlap_and_keep_arrival_order(
    domain_env: object,
) -> None:
    """Три кадра одного чата подряд: разбор каждого целиком, в порядке прихода."""
    start_inspection(CHAT_A, "Белград 2", "planned", "ru")
    parse = SlowParse()

    await run_polling(
        [captioned(f"a{i}", CHAT_A) for i in range(1, 4)], parse, settle=SLOW_SEC * 3 + 0.6
    )

    assert parse.log == [
        ("enter", "a1"),
        ("exit", "a1"),
        ("enter", "a2"),
        ("exit", "a2"),
        ("enter", "a3"),
        ("exit", "a3"),
    ], f"обновления одного чата перекрылись или переставились: {parse.log}"


async def test_a_slow_chat_does_not_hold_another_chat(domain_env: object) -> None:
    """Чат Б получает разбор, пока чат А ещё разбирается: чаты идут параллельно."""
    start_inspection(CHAT_A, "Белград 2", "planned", "ru")
    start_inspection(CHAT_B, "Белград 3", "planned", "ru")
    parse = SlowParse()

    await run_polling(
        [captioned("a1", CHAT_A), captioned("b1", CHAT_B)], parse, settle=SLOW_SEC + 0.5
    )

    assert ("enter", "b1") in parse.log and ("exit", "a1") in parse.log
    assert parse.log.index(("enter", "b1")) < parse.log.index(("exit", "a1")), (
        f"чат Б дождался конца разбора чата А: {parse.log}"
    )


async def test_chat_lock_serialises_one_chat_through_the_dispatcher(domain_env: object) -> None:
    """То же без опроса: два обновления одного чата, поданные разом, идут по очереди."""
    start_inspection(CHAT_A, "Белград 2", "planned", "ru")
    parse = SlowParse()
    session = RecordingSession()
    bot = Bot(token="111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    dp = app.build_dispatcher(SETTINGS, on_material=parse, album_window=5.0)

    first, second = captioned("s1", CHAT_A), captioned("s2", CHAT_A)
    await asyncio.gather(dp.feed_update(bot, first), dp.feed_update(bot, second))

    assert parse.log == [
        ("enter", "s1"),
        ("exit", "s1"),
        ("enter", "s2"),
        ("exit", "s2"),
    ], f"два обновления одного чата наехали друг на друга: {parse.log}"


async def test_lock_registry_is_empty_after_work_and_after_a_failure() -> None:
    """Запись замка живёт, пока в чате есть обновление: после работы и после отказа её нет."""
    locks = ChatLocks()
    middleware = ChatLockMiddleware(locks)
    seen: list[int] = []

    class Chat:
        id = 7

    async def ok(event: object, data: dict[str, Any]) -> str:
        seen.append(len(locks))
        return "ok"

    async def boom(event: object, data: dict[str, Any]) -> None:
        raise RuntimeError("хендлер упал")

    assert await middleware(ok, text_message("x"), {"event_chat": Chat()}) == "ok"
    with pytest.raises(RuntimeError):
        await middleware(boom, text_message("x"), {"event_chat": Chat()})

    assert seen == [1], "пока обновление идёт, замок чата в реестре есть"
    assert len(locks) == 0, "замок остался в реестре после обновления"


async def test_event_without_a_chat_goes_without_a_lock() -> None:
    locks = ChatLocks()
    middleware = ChatLockMiddleware(locks)
    called: list[int] = []

    async def handler(event: object, data: dict[str, Any]) -> None:
        called.append(len(locks))

    await middleware(handler, text_message("x"), {})

    assert called == [0]


async def test_chat_lock_sits_on_the_update_level_before_access_checks() -> None:
    """Замок на уровне апдейта: доступ и выбор языка (с их походами в базу) — уже под очередью."""
    dp: Dispatcher = app.build_dispatcher(SETTINGS)

    assert any(isinstance(m, ChatLockMiddleware) for m in dp.update.outer_middleware)
