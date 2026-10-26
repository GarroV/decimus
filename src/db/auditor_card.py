"""Имя проверяющего из карточки человека (D642).

Карточка — учётка в «Людях»; имя и фамилия лежат в `web_users.display_name`
(`0065`, заполняется при входе через Google), а написание латиницей — в
`display_name_latin` (`0100`, D644, правит админ): заполнено — берётся оно, пусто
— имя из `display_name` (перевод в латиницу делает `spell_name` у вызывающего).
Найти карточку можно двумя путями: по Telegram ID через привязку бота (`bot_bindings`) — для бота и
мини-аппа; по пространству и логину вошедшей учётки — для MCP и веба.

Сбой чтения не должен останавливать старт проверки: `*_or_none` пишут строку
в журнал и отдают `None`, а выбор откатывается к следующему источнику
(`AUDITOR_NAMES`, затем профиль Telegram).
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.log_ids import log_id

from .errors import DbError
from .web_access import _connected

logger = logging.getLogger(__name__)

_BY_TELEGRAM_SQL = """
    select coalesce(nullif(btrim(u.display_name_latin), ''), u.display_name)
      from bot_bindings b join web_users u on u.id = b.user_id
     where b.unbound_at is null and u.disabled_at is null and b.telegram_id = %s
"""
_BY_LOGIN_SQL = """
    select coalesce(nullif(btrim(display_name_latin), ''), display_name) from web_users
     where tenant_code = %s and login = %s and disabled_at is null
"""


def _fetch_name(sql: str, params: tuple[Any, ...], зачем: str) -> str | None:
    with _connected(зачем) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    name = (row[0] or "").strip() if row else ""
    return name or None


def name_by_telegram(telegram_id: int) -> str | None:
    """Имя из карточки, к которой привязан Telegram ID; нет привязки или имени — `None`."""
    return _fetch_name(_BY_TELEGRAM_SQL, (telegram_id,), "прочитать имя проверяющего")


def name_by_login(tenant: str, login: str) -> str | None:
    """Имя из карточки учётки (пространство, логин); нет карточки или имени — `None`."""
    return _fetch_name(
        _BY_LOGIN_SQL, (tenant.strip(), login.strip().lower()), "прочитать имя проверяющего"
    )


def name_by_telegram_or_none(telegram_id: int) -> str | None:
    """`name_by_telegram`, не роняющий вызывающего: сбой — в журнал и `None`."""
    try:
        return name_by_telegram(telegram_id)
    except DbError:
        logger.exception(
            "Имя проверяющего: карточка по Telegram %s не прочиталась, берём следующий источник",
            log_id(telegram_id),
        )
        return None


def name_by_login_or_none(tenant: str, login: str) -> str | None:
    """`name_by_login`, не роняющий вызывающего: сбой — в журнал и `None`."""
    try:
        return name_by_login(tenant, login)
    except DbError:
        logger.exception(
            "Имя проверяющего: карточка %s/%s не прочиталась, берём следующий источник",
            tenant,
            log_id(login),
        )
        return None
