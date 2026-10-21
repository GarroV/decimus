"""Очередь внутри чата при параллельной обработке обновлений (F-122, #1006).

Бот обрабатывает обновления задачами: медленная голосовая или тормозящий
провайдер одного чата не должны держать ответы всем остальным. Но порядок
внутри чата — не оптимизация, а требование T059: пачка кадров и комментариев,
пришедшая разом после потери связи, обязана разобраться так, как если бы её
слали по одному (FIFO-связывание кадров с комментариями, `src/bot/material.py`),
а состояние диалога лежит в `MemoryStorage`, где два обновления одного чата
наехали бы друг на друга между чтением и записью.

Поэтому обновления ОДНОГО чата идут строго по очереди — под замком этого чата,
разные чаты — параллельно. Замок берётся самой внешней мидлварью апдейта, до
доступа и выбора языка: всё, что обновление делает, включая их походы в базу,
укладывается в его очередь.

Порядок очереди даёт сам `asyncio.Lock`: ожидающие просыпаются по очереди
прихода, а задачи на обновления aiogram заводит в порядке получения и до первого
ожидания в мидлвари не уступают цикл. Поэтому «кто пришёл раньше, тот и первым
берёт замок».

Границы. Замок держится на ОДНО обновление и не пускает в чат другие
обновления того же чата — но не фоновые задачи, которые хендлер сам завёл
(таймер окна альбома, сборщики кадров): их порядок — их собственный. Замок
процессный: вторая копия бота его не видит (вариант Б задачи F-122 — вне
этого блока).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

#: Ключ чата события в `data` апдейта: его кладёт `UserContextMiddleware`
#: aiogram, и он есть у сообщений, нажатий и прочих событий с чатом.
EVENT_CHAT_KEY = "event_chat"

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


@dataclass
class _Slot:
    """Замок чата и сколько обновлений его держат или ждут."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class ChatLocks:
    """Реестр замков по чатам. Запись живёт, пока в чате есть обновление."""

    def __init__(self) -> None:
        self._slots: dict[int, _Slot] = {}

    def __len__(self) -> int:
        return len(self._slots)

    @asynccontextmanager
    async def hold(self, chat_id: int) -> AsyncIterator[None]:
        """Занять очередь чата; на выходе — освободить и убрать запись, если она последняя.

        Запись убирается в `finally`, в том числе при отмене задачи: замок,
        оставшийся в реестре без владельца, был бы утечкой на каждый чат.
        """
        slot = self._slots.setdefault(chat_id, _Slot())
        slot.users += 1
        try:
            async with slot.lock:
                yield
        finally:
            slot.users -= 1
            if slot.users == 0:
                del self._slots[chat_id]


class ChatLockMiddleware(BaseMiddleware):
    """Обновления одного чата — по очереди, разных чатов — параллельно.

    Вешается на `dispatcher.update` первой из внешних мидлварей. События без
    чата (например, встроенные запросы) идут без замка: очередь им не нужна.
    """

    def __init__(self, locks: ChatLocks | None = None) -> None:
        self._locks = locks if locks is not None else ChatLocks()

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = data.get(EVENT_CHAT_KEY)
        if chat is None:
            return await handler(event, data)
        async with self._locks.hold(chat.id):
            return await handler(event, data)
