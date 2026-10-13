"""Меню учётки (D468): состояние подключений для строки «Подключения».

Меню открывается из блока учётки на КАЖДОЙ странице, а состояния подключений
(токен Claude, бот, Google) стоят запросов в базу. Поэтому страница рисует меню
без них, а эту группу браузер подгружает фрагментом при первом открытии
(`GET /settings/menu`): три запроса платит тот, кто меню открыл, а не каждая
страница. Источники те же, что у страницы «Настройки», — вторых нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.db import bot_links
from src.db.errors import DbError

from . import users_claude, users_mcp
from .db_refusal import note_target_mismatch

State = Literal["on", "off", "unknown"]


@dataclass(frozen=True)
class Connection:
    """Одна строка группы: название (ключ текста), состояние и раздел «Настроек»."""

    key: str
    anchor: str
    state: State


def _claude(user_id: str, mcp_url: str | None) -> State:
    """Есть живой личный токен или подключение входом через сайт."""
    токен = users_mcp.own_status(user_id)
    if not токен.known:
        return "unknown"
    if токен.expires_at:
        return "on"
    вход = users_claude.claude_connect(user_id, mcp_url)
    if вход.enabled and not вход.known:
        return "unknown"
    return "on" if вход.connections else "off"


def _bot(user_id: str) -> State:
    try:
        return "on" if bot_links.binding_of(user_id) else "off"
    except DbError as exc:
        note_target_mismatch(exc)
        return "unknown"


def connections(
    user_id: str, *, email: str | None, google_enabled: bool, mcp_url: str | None
) -> list[Connection]:
    """Три подключения учётки в том порядке, в каком они на странице «Настройки»."""
    return [
        Connection("settings.claude.title", "claude", _claude(user_id, mcp_url)),
        Connection("settings.bot.title", "bot", _bot(user_id)),
        Connection("settings.google.title", "google", "on" if email and google_enabled else "off"),
    ]
