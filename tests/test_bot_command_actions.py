"""Команды бота сведены к матрице: каждая названа в `COMMAND_ACTIONS` действием каталога.

Команда без строки там — команда, о правах которой никто не думал: этот набор
называет её по имени. Вход в бота спрашивает `inspection.conduct` (мидлварь),
`/stops` — сверх него своё действие.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from bot_harness import AUDITOR_ID

from src.bot.access import COMMAND_ACTIONS, FIELD_ACTION, role_closed
from src.bot.app import MENU_COMMANDS, build_dispatcher
from src.bot.config import BotSettings
from src.db.bot_links import Binding, Standing
from src.domain.permissions import ACTION_CODES, role_may

SETTINGS = BotSettings(token="unused-in-tests", mode="polling")


def _команды(router: Router) -> set[str]:
    найдено: set[str] = set()
    for обработчик in router.message.handlers:
        for фильтр in обработчик.filters or ():
            if isinstance(фильтр.callback, Command):
                найдено |= {str(c) for c in фильтр.callback.commands}
    for вложенный in router.sub_routers:
        найдено |= _команды(вложенный)
    return найдено


def _все_команды() -> set[str]:
    dispatcher: Dispatcher = build_dispatcher(SETTINGS)
    return _команды(dispatcher)


def test_каждая_команда_бота_сведена_к_действию() -> None:
    assert _все_команды() == set(COMMAND_ACTIONS)


def test_действия_команд_из_каталога() -> None:
    assert set(COMMAND_ACTIONS.values()) <= ACTION_CODES


def test_меню_не_шире_карты() -> None:
    assert {имя for имя, _ in MENU_COMMANDS} <= set(COMMAND_ACTIONS)


def _положение(role: str, tenant: str = "HQ") -> Standing:
    return Standing(
        binding=Binding(
            user_id="u1",
            login="l",
            tenant=tenant,
            telegram_id=AUDITOR_ID,
            bound_at=datetime(2026, 10, 12, tzinfo=UTC),
            role=role,
        ),
        ever_bound=True,
    )


def test_вход_в_бота_по_матрице() -> None:
    """Поле открыто ровно тем, у кого в матрице `inspection.conduct` (D420, D440)."""
    for role, tenant in (
        ("superadmin", "HQ"),
        ("admin", "HQ"),
        ("developer", "HQ"),
        ("control", "HQ"),
        ("guest", "HQ"),
        ("admin", "RS"),
        ("auditor", "RS"),
        ("auditor", "HQ"),
    ):
        закрыт = role_closed(_положение(role, tenant))
        assert закрыт is not role_may(role, tenant, FIELD_ACTION), (role, tenant)
    assert role_closed(_положение("control"))
    assert role_closed(_положение("guest"))
    assert not role_closed(_положение("developer"))
