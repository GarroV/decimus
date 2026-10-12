"""Что предлагает начало проверки: открытые чек-листы пространства человека.

Один источник на мастер бота и на мастер мини-аппа (D392): оба спрашивают
«по какому чек-листу» из одного и того же списка и одинаково переживают отказ
чтения.
"""

from __future__ import annotations

import logging

from src.domain.bot_checklists import BotChecklist, available
from src.domain.config import check_environment
from src.domain.errors import DomainError

logger = logging.getLogger(__name__)


def open_checklists(space: str) -> list[BotChecklist] | None:
    """Открытые в боте чек-листы пространства аудитора — или `None`, если их не прочитать."""
    try:
        return available(check_environment(), tenant=space)
    except (DomainError, OSError, ValueError):
        logger.exception("список чек-листов для бота не прочитался")
        return None
