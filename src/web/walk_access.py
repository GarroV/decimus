"""Кого пускает мини-апп — ровно тех, кого пускает бот (D372).

До D372 вход в мини-апп был только кнопкой под сообщением бота, а сообщение
бот присылает лишь тем, кого сам пустил. Подписи Telegram хватало: открыть
страницу мог только свой. Кнопка меню бота меняет это — её видит каждый, кто
открыл бота, в том числе тот, кого бот не обслуживает. Поэтому мини-апп
сверяет человека тем же правилом, что мидлварь доступа бота
(`bot.access.space_from`): привязка учётки, затем связки по приглашениям.
Список `ALLOWED_TELEGRAM_IDS` снят (D517). Ответ — пространство человека, оно
же нужно выпуску токена MCP и началу проверки.
"""

from __future__ import annotations

import logging

from src.bot.access import role_closed, space_from
from src.bot.errors import BotConfigError
from src.bot.roster import Roster
from src.db import bot_links
from src.domain import check_environment

logger = logging.getLogger(__name__)


def _roster() -> Roster | None:
    """Связки по приглашениям. Битый файл — без них: пускает только привязка."""
    try:
        return Roster.load(check_environment().state_dir)
    except BotConfigError:
        logger.exception("Обход: связки доступа не прочитались — сверка без них")
        return None


def space_of(chat_id: int) -> str | None:
    """Пространство человека или `None` — бот его не пускает.

    База молчит — `DbError` наверх: сверить нечем, а отвечать «пускаю»
    вслепую нельзя.
    """
    положение = bot_links.standing(chat_id)
    return space_from(chat_id, положение, roster=_roster())


def role_is_closed(chat_id: int) -> bool:
    """Учётка человека жива, но её роли поле закрыто (контроль, D420, аудит 12.10 F-024).

    Отдельный вопрос, а не ещё одно значение `space_of`: отказ по роли
    объясняется человеку словами, а отказ постороннему — нет. Правило то же,
    что у бота (`bot.access.role_closed`). База молчит — `DbError` наверх.
    """
    return role_closed(bot_links.standing(chat_id))
