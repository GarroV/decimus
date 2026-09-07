"""Доступ по списку разрешённых Telegram ID (задача T050, привод — #230).

Незнакомому отправителю бот не отвечает ничего осмысленного (принцип
безопасности проекта, `docs/forge/constitution.md`): апдейт от него до хендлера
не доходит вовсе, а не получает отдельное сообщение об отказе — иначе бот сам
подтверждает постороннему, что он существует и что этот ID неверный.

Дверей три, и порядок между ними жёсткий:

1. ID назван окружением стенда (`ALLOWED_TELEGRAM_IDS`) — как было всегда;
2. ID уже узнан по приглашению (`src.bot.roster`);
3. ID незнаком, но юзернейм из этого же апдейта ждут (`src.bot.invites`) —
   тогда связка записывается, и человек входит.

Третья дверь существует потому, что числовой ID нового аудитора неоткуда
взять заранее: он приходит только в апдейте. Она же — единственное место, где
юзернейм вообще что-то решает: сразу после активации ключом становится ID, и
отпущенный юзернейм, занятый посторонним, больше не открывает ничего.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from .invites import InviteSource
from .roster import Roster

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


def is_allowed(user_id: int | None, allowed_ids: frozenset[int]) -> bool:
    """Разрешён ли этот Telegram ID. Отсутствие ID (служебное обновление) — нет."""
    return user_id is not None and user_id in allowed_ids


class AccessMiddleware(BaseMiddleware):
    """Внешняя мидлварь на `message` и `callback_query`: чужого не пускает дальше."""

    def __init__(
        self,
        allowed_ids: frozenset[int],
        invites: InviteSource | None = None,
        roster: Roster | None = None,
    ) -> None:
        self._allowed_ids = allowed_ids
        self._invites = invites
        self._roster = roster

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = user.id if user is not None else None
        if not self._may_pass(user_id, getattr(user, "username", None)):
            logger.warning("отклонено обновление от постороннего Telegram ID %s", user_id)
            return None
        return await handler(event, data)

    def _may_pass(self, user_id: int | None, username: str | None) -> bool:
        if is_allowed(user_id, self._allowed_ids):
            return True
        if user_id is None:
            return False
        if self._roster is not None and self._roster.knows(user_id):
            return True
        return self._activate(user_id, username)

    def _activate(self, user_id: int, username: str | None) -> bool:
        """Пустить по приглашению и запомнить связку — или не пустить.

        Приглашение срабатывает ровно один раз. Уже использованное молчит даже
        на верный юзернейм: владелец мог его отпустить, а занявший юзернейм
        посторонний — не тот человек, которого приглашали.
        """
        if self._invites is None or self._roster is None or not username:
            return False
        invite = self._invites.find(username)
        if invite is None or self._roster.username_used(invite.username):
            return False
        self._roster.activate(user_id, invite)
        logger.info(
            "принят по приглашению: @%s — Telegram ID %s, дальше доступ по ID",
            invite.username,
            user_id,
        )
        return True
