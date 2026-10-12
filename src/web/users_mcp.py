"""Личный токен Claude на своей карточке: выпустить себе и отозвать (D447, D448).

Доступ к Claude никто никому не выдаёт (D448): человек с действующей учёткой
сам выпускает себе токен — здесь, в настройках своего профиля, или в боте и
мини-аппе. Выпуск один на все двери (`mcp_access.issue_for_account`); что можно
в Claude, решает роль учётки; доступ кончается отключением учётки или сменой
роли (триггер миграции `0059` гасит токены сам).

Блок стоит только на СВОЕЙ карточке, и учётка берётся из сессии, а не из
формы: выпустить или отозвать чужой токен отсюда нечем.

Команду собирает тот же модуль, что у бота и мини-аппа (`src/bot/mcp_setup.py`):
одна строка в терминале кладёт мост и запись Claude Desktop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime

from src.bot.mcp_setup import MCP_URL_VAR, setup_command
from src.db import mcp_access
from src.db.errors import DbError

from .db_refusal import note_target_mismatch

#: Заглушка адреса, когда стенд его не назвал, — как у бота: видна в команде
#: ровно там, где стоял бы адрес, а не подменяется догадкой.
URL_PLACEHOLDER = "SERVER_ADDRESS"


@dataclass(frozen=True)
class TokenStatus:
    """Живой токен вошедшего глазами карточки."""

    known: bool
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Issued:
    """Выпущенная команда — живёт до ответа страницы, нигде не хранится.

    `repr=False` у команды: в ней токен, а `repr` уезжает в трейсбек и журнал.
    """

    command: str = field(repr=False)
    expires_at: datetime | None = None
    replaced: bool = False


def own_status(user_id: str | None) -> TokenStatus:
    """Есть ли у вошедшего живой токен и до какого числа. База молчит — «не знаем»."""
    if user_id is None:
        return TokenStatus(known=True)
    try:
        return TokenStatus(known=True, expires_at=mcp_access.live_token_expiry(user_id))
    except DbError as exc:
        note_target_mismatch(exc)
        return TokenStatus(known=False)


def issue_own(user_id: str) -> Issued:
    """Выпустить вошедшему токен и собрать команду настройки. Отказ базы — наверх."""
    выпущен = mcp_access.issue_for_account(user_id)
    url = (os.environ.get(MCP_URL_VAR) or "").strip() or URL_PLACEHOLDER
    return Issued(
        command=setup_command(url=url, token=выпущен.value),
        expires_at=выпущен.expires_at,
        replaced=выпущен.replaced_previous,
    )
