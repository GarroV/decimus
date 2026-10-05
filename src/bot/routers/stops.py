"""`/stops` — счётчик отказов мастера за период, только для круга админов (#436).

Владелец открывает его сам: сообщений о повторяющихся отказах бот никому не
шлёт, такие отправки — только по явному «да» владельца на текст и адресатов.
Здесь бот отвечает лишь тому, кто спросил.

Кого пускать — решает тот же заслон, что у `/mcp` (`_guard`): круг админов,
который основатель задаёт настройкой, а остальных база. Второго списка «кто
админ» в боте не заводится: два списка разошлись бы молча. Команды нет в меню —
меню видят все аудиторы, а им она отвечает отказом.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.domain.errors import DomainError

from .. import stops
from ..config import BotSettings
from ..lang import chat_ui_lang
from ..texts import t
from .mcp import _guard

logger = logging.getLogger(__name__)

STOPS_COMMAND = "stops"
#: Период по умолчанию и предел: дольше года счётчик не спрашивают.
DEFAULT_DAYS = 7
MAX_DAYS = 366


def _days(command: CommandObject) -> int | None:
    """Период в днях из аргумента. Пусто — неделя; не число или вне 1…366 — `None`."""
    raw = (command.args or "").strip()
    if not raw:
        return DEFAULT_DAYS
    if not raw.isdigit():
        return None
    days = int(raw)
    return days if 1 <= days <= MAX_DAYS else None


def build_stops_router(settings: BotSettings) -> Router:
    router = Router(name="stops")

    @router.message(Command(STOPS_COMMAND))
    async def on_stops(message: Message, command: CommandObject) -> None:
        if await _guard(message, settings) is None:
            return
        lang = chat_ui_lang(message.chat.id)
        days = _days(command)
        if days is None:
            await message.answer(t("stops.bad_days", lang, limit=MAX_DAYS))
            return
        since = datetime.now(UTC) - timedelta(days=days)
        try:
            counts = await asyncio.to_thread(stops.count_stops, since)
        except (OSError, DomainError):
            logger.exception("счётчик отказов не прочитался")
            await message.answer(t("stops.unreadable", lang))
            return
        if not counts:
            await message.answer(t("stops.empty", lang, days=days))
            return
        lines = [
            t("stops.line", lang, step=c.step, reason=c.reason, times=c.times, people=c.people)
            for c in counts
        ]
        await message.answer("\n".join([t("stops.header", lang, days=days), *lines]))

    return router
