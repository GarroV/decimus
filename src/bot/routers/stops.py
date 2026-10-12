"""`/stops` — счётчик отказов мастера за период, только админам (#436).

Владелец открывает его сам: сообщений о повторяющихся отказах бот никому не
шлёт, такие отправки — только по явному «да» владельца на текст и адресатов.
Здесь бот отвечает лишь тому, кто спросил.

Кого пускать — решает роль учётки, к которой привязан бот (`is_admin_role`:
админ и главный админ). До D448 заслоном был круг доступа к MCP; круг снят, а
второго списка «кто админ» в боте не заводится — он разошёлся бы с ролями
учёток молча. Команды нет в меню — меню видят все аудиторы, а им она отвечает
отказом.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.db import bot_links
from src.db.errors import DbError
from src.domain.errors import DomainError
from src.domain.log_ids import log_id
from src.domain.tenants import is_admin_role

from .. import stops
from ..lang import chat_ui_lang
from ..texts import t

logger = logging.getLogger(__name__)

STOPS_COMMAND = "stops"
#: Период по умолчанию и предел. Предел — срок хранения счётчика (#501):
#: дальше него строк нет, и период длиннее молча считал бы меньше спрошенного.
DEFAULT_DAYS = 7
MAX_DAYS = stops.STOPS_RETENTION_DAYS


def _days(command: CommandObject) -> int | None:
    """Период в днях из аргумента. Пусто — неделя; не число или вне 1…MAX_DAYS — `None`."""
    raw = (command.args or "").strip()
    if not raw:
        return DEFAULT_DAYS
    if not raw.isdigit():
        return None
    days = int(raw)
    return days if 1 <= days <= MAX_DAYS else None


async def _admin(message: Message, lang: str) -> bool:
    """Админ ли спросивший — по роли его учётки прямо сейчас; иначе ответ отказом."""
    user = message.from_user
    if user is None:
        return False
    try:
        положение = await asyncio.to_thread(bot_links.standing, user.id)
    except DbError:
        logger.exception("привязка %s не прочиталась для /stops", log_id(user.id))
        await message.answer(t("stops.unreadable", lang))
        return False
    if положение.binding is None or not is_admin_role(положение.binding.role):
        await message.answer(t("stops.not_admin", lang))
        return False
    return True


def build_stops_router() -> Router:
    router = Router(name="stops")

    @router.message(Command(STOPS_COMMAND))
    async def on_stops(message: Message, command: CommandObject) -> None:
        lang = chat_ui_lang(message.chat.id)
        if not await _admin(message, lang):
            return
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
