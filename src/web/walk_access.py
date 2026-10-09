"""Кого пускает мини-апп — ровно тех, кого пускает бот (D372).

До D372 вход в мини-апп был только кнопкой под сообщением бота, а сообщение
бот присылает лишь тем, кого сам пустил. Подписи Telegram хватало: открыть
страницу мог только свой. Кнопка меню бота меняет это — её видит каждый, кто
открыл бота, в том числе тот, кого бот не обслуживает. Поэтому мини-апп
сверяет человека тем же правилом, что мидлварь доступа бота
(`bot.access.space_from`): привязка учётки, затем список окружения и связки
по приглашениям. Ответ — пространство человека, оно же нужно выпуску токена
MCP и началу проверки.
"""

from __future__ import annotations

import logging

from src.bot.access import space_from
from src.bot.errors import BotConfigError
from src.bot.roster import Roster
from src.db import bot_links
from src.domain import check_environment

from .walk_auth import WalkSettings

logger = logging.getLogger(__name__)


def _roster() -> Roster | None:
    """Связки по приглашениям. Битый файл — без них: пускает привязка и список."""
    try:
        return Roster.load(check_environment().state_dir)
    except BotConfigError:
        logger.exception("Обход: связки доступа не прочитались — сверка без них")
        return None


def space_of(chat_id: int, conf: WalkSettings) -> str | None:
    """Пространство человека или `None` — бот его не пускает.

    База молчит — `DbError` наверх: сверить нечем, а отвечать «пускаю»
    вслепую нельзя.
    """
    положение = bot_links.standing(chat_id)
    return space_from(chat_id, положение, allowed_ids=conf.allowed_ids, roster=_roster())
