"""Список Telegram ID из окружения больше не вход (D517, аудит 13.10 F-112).

До D517 бот и мини-апп пускали ID из `ALLOWED_TELEGRAM_IDS` как сотрудника УК
без учётки (совместимость D290). Для такого человека не работало правило
карты доступа «доступ кончается отключением учётки или сменой роли»:
отключать было нечего. Теперь вход только по привязке к живой учётке — ID
из окружения без учётки получает то же молчание, что посторонний.
"""

from __future__ import annotations

import pytest
from bot_harness import feed, make_bot, text_message

from src.bot.access import BindingCache
from src.bot.app import build_dispatcher
from src.bot.config import load_bot_settings
from src.db.bot_links import NEVER_BOUND
from src.web import walk_access

pytestmark = pytest.mark.asyncio

ID_ИЗ_СПИСКА = 111
ОКРУЖЕНИЕ = {"TELEGRAM_BOT_TOKEN": "1:x", "ALLOWED_TELEGRAM_IDS": str(ID_ИЗ_СПИСКА)}


async def test_бот_не_пускает_id_из_списка_без_учётки(domain_env: object) -> None:
    dp = build_dispatcher(
        load_bot_settings(ОКРУЖЕНИЕ), bindings=BindingCache(standing=lambda _tg: NEVER_BOUND)
    )
    bot, session = make_bot()

    await feed(dp, bot, text_message("/start", user_id=ID_ИЗ_СПИСКА, chat_id=ID_ИЗ_СПИСКА))

    assert session.calls == [], "ID из окружения без учётки получил ответ бота"


def test_мини_апп_не_пускает_id_из_списка_без_учётки(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(walk_access.bot_links, "standing", lambda _tg: NEVER_BOUND)
    monkeypatch.setattr(walk_access, "_roster", lambda: None)

    пространство = walk_access.space_of(ID_ИЗ_СПИСКА)

    assert пространство is None, "мини-апп пустил ID из окружения без учётки"
