"""Обновления разных чатов идут параллельно, одного чата — строго по очереди (GHSA-7gm6-hc9m-w3vc).

Опрос запускается с `handle_as_tasks=True`: каждое обновление — своя задача, и
голосовое одного аудитора (ffmpeg и расшифровка — минуты) не держит ответы
остальным. Но порядок внутри чата обязателен: состояние проверки — файлы с
`flock`, а шаги мастера лежат в `MemoryStorage`; две записи одного чата не должны
гоняться. Поэтому мидлварь уровня `Update` берёт замок чата.

Замки берутся в порядке прихода: задачи стартуют в порядке создания, до замка
нет ни одной паузы, а `asyncio.Lock` отдаёт замок по очереди ожидания.
Общий предел одновременных обновлений — семафор ПОСЛЕ замка чата: ждущие своей
очереди обновления одного чата не занимают места чужим.

Состояние бота по-прежнему в одном процессе (FSM в памяти, проверки в файлах):
это отложено владельцем, и два процесса этот замок не согласует.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

#: Сколько обновлений разных чатов обрабатывается одновременно. Каждое держит
#: поток или подпроцесс (to_thread, ffmpeg), а потоков в пуле по умолчанию
#: `min(32, cpu + 4)`; запас над ним только копил бы очередь внутри пула.
MAX_CONCURRENT_UPDATES = 16


def chat_key(update: Update) -> int | None:
    """Чат сообщения или кнопки; у прочих обновлений чата нет — `None` (без замка)."""
    message = update.message or update.edited_message
    if message is not None:
        return message.chat.id
    query = update.callback_query
    if query is not None:
        if query.message is not None:
            return query.message.chat.id
        return query.from_user.id  # кнопка из встроенного режима: сообщения нет
    return None


class ChatSerialMiddleware(BaseMiddleware):
    """Замок на чат плюс общий предел одновременных обновлений."""

    def __init__(self, limit: int = MAX_CONCURRENT_UPDATES) -> None:
        self._slots = asyncio.Semaphore(limit)
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        key = chat_key(event) if isinstance(event, Update) else None
        if key is None:
            async with self._slots:
                return await handler(event, data)
        lock = self._enter(key)
        try:
            async with lock, self._slots:
                return await handler(event, data)
        finally:
            self._leave(key)

    def _enter(self, key: int) -> asyncio.Lock:
        lock, users = self._locks.get(key) or (asyncio.Lock(), 0)
        self._locks[key] = (lock, users + 1)
        return lock

    def _leave(self, key: int) -> None:
        lock, users = self._locks[key]
        if users <= 1:
            del self._locks[key]
        else:
            self._locks[key] = (lock, users - 1)
