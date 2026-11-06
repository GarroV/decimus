"""Личный токен Claude в «Настройках»: выпустить себе и отозвать (D447, D448).

Доступ к Claude никто никому не выдаёт (D448): человек с действующей учёткой
сам выпускает себе токен — в «Настройках» своего профиля, в боте или
мини-аппе. Выпуск один на все двери (`mcp_access.issue_for_account`); что можно
в Claude, решает роль учётки; доступ кончается отключением учётки или сменой
роли (триггер миграции `0059` гасит токены сам).

Блок стоит только в «Настройках», и учётка берётся из сессии, а не из
формы: выпустить или отозвать чужой токен отсюда нечем.

Команду собирает `src/bot/mcp_setup.py`: одна строка в терминале кладёт мост и запись
Claude Desktop либо регистрирует мост в настольном ChatGPT (D695).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.bot.mcp_setup import MCP_URL_VAR, chatgpt_setup_command, setup_command
from src.db import mcp_access
from src.db.errors import DbError

from .db_refusal import note_target_mismatch

#: Заглушка адреса, когда стенд его не назвал, — как у бота: видна в команде
#: ровно там, где стоял бы адрес, а не подменяется догадкой.
URL_PLACEHOLDER = "SERVER_ADDRESS"


TARGET_CLAUDE = "claude"
TARGET_CHATGPT = "chatgpt"
TARGETS = (TARGET_CLAUDE, TARGET_CHATGPT)


#: За сколько дней до конца срока карточка предупреждает, что токен пора перевыпустить (#1440).
EXPIRY_WARN_DAYS = 7


@dataclass(frozen=True)
class TokenStatus:
    """Живой токен вошедшего глазами карточки."""

    known: bool
    expires_at: datetime | None = None

    def days_left(self, now: datetime | None = None) -> int | None:
        """Дней до конца срока, вверх (последний день — 1); живого токена нет — `None`."""
        if self.expires_at is None:
            return None
        end = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        left = (end - (now or datetime.now(UTC))).total_seconds()
        return max(1, -(-int(left) // 86400))

    def expiring_soon(self, now: datetime | None = None) -> bool:
        """Срок подходит к концу: предупредить на карточке, пока токен ещё работает."""
        left = self.days_left(now)
        return left is not None and left <= EXPIRY_WARN_DAYS


@dataclass(frozen=True)
class Issued:
    """Выпущенная команда — живёт до ответа страницы, нигде не хранится.

    `repr=False` у команды: в ней токен, а `repr` уезжает в трейсбек и журнал.
    """

    command: str = field(repr=False)
    expires_at: datetime | None = None
    replaced: bool = False
    #: Для какой программы команда: `claude` (Claude Desktop) или `chatgpt` (D695).
    #: Токен один и тот же, различается только установщик за строкой.
    target: str = TARGET_CLAUDE


def own_status(user_id: str | None) -> TokenStatus:
    """Есть ли у вошедшего живой токен и до какого числа. База молчит — «не знаем»."""
    if user_id is None:
        return TokenStatus(known=True)
    try:
        return TokenStatus(known=True, expires_at=mcp_access.live_token_expiry(user_id))
    except DbError as exc:
        note_target_mismatch(exc)
        return TokenStatus(known=False)


def issue_own(user_id: str, target: str = TARGET_CLAUDE) -> Issued:
    """Выпустить вошедшему токен и собрать команду настройки. Отказ базы — наверх.

    Токен у учётки один (миграция `0059`): выпуск для ChatGPT гасит и тот, что стоит у
    Claude Desktop, и наоборот. Установщик за строкой — по `target`.
    """
    if target not in TARGETS:
        raise ValueError(f"неизвестная программа для токена: {target}")
    выпущен = mcp_access.issue_for_account(user_id)
    url = (os.environ.get(MCP_URL_VAR) or "").strip() or URL_PLACEHOLDER
    build = chatgpt_setup_command if target == TARGET_CHATGPT else setup_command
    return Issued(
        command=build(url=url, token=выпущен.value),
        expires_at=выпущен.expires_at,
        replaced=выпущен.replaced_previous,
        target=target,
    )
