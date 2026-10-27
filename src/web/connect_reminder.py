"""Напоминание на «Главной»: привяжите бота и подключите Claude (27.10.2026).

По просьбе владельца 27.10.2026 веб напоминает привязать бота и подключить Claude: люди
команды заводились учётками, а бот и Claude не подключали, и бот молча
отказывал. Состояния — из меню учётки (`account_menu.connections`), вторых
источников нет. Только «Главная», а не каждая страница: состояния стоят
запросов в базу. «Не знаю» (база молчит) не напоминает — показ только по
факту «не подключено».
"""

from __future__ import annotations

from flask import current_app

from src.domain.permissions import role_may

from . import account_menu, auth, users_claude
from .settings_screen import BOT_USERNAME_KEY

#: Действие «вести проверку»: бот и обход нужны только тем, кто их ведёт (D420).
_FIELD_ACTION = "inspection.conduct"


def missing() -> tuple[str, ...]:
    """Разделы «Настроек», которые вошедшему стоит подключить: `claude`, `bot`."""
    вошедший = auth.current_account()
    if вошедший is None:
        return ()
    строки = account_menu.connections(
        str(вошедший.id),
        email=вошедший.email,
        google_enabled=False,
        mcp_url=current_app.config.get(users_claude.MCP_URL_KEY),
    )
    состояние = {строка.anchor: строка.state for строка in строки}
    нужен_бот = bool(current_app.config.get(BOT_USERNAME_KEY)) and role_may(
        вошедший.role, auth.current_tenant(), _FIELD_ACTION
    )
    итог = []
    if нужен_бот and состояние.get("bot") == "off":
        итог.append("bot")
    if состояние.get("claude") == "off":
        итог.append("claude")
    return tuple(итог)
