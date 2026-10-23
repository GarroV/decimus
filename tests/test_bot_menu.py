"""Меню команд бота: состав, названия, чего в нём нет (D087, D086, D626).

Выделено из `tests/test_bot_mcp_setup.py`, когда пункт «Установка MCP» снят из
бота (D626): проверки состава меню к MCP не относились и остаются.
"""

from __future__ import annotations

import pytest
from bot_harness import make_bot

from src.bot.app import MENU_COMMANDS, announce_commands

pytestmark = pytest.mark.asyncio


async def test_общее_меню_объявлено_без_подключения_claude_и_круга(domain_env: object) -> None:
    """Подключения Claude в боте нет (D626), круга доступа тоже (D448)."""
    bot, session = make_bot()

    await announce_commands(bot)

    объявлено = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    assert объявлено, "команды в меню не объявлены вовсе"
    assert all(
        c.scope is None or type(c.scope).__name__ == "BotCommandScopeDefault" for c in объявлено
    )
    имена = {c.command for c in объявлено[0].commands}
    for пункт in ("mcp", "mcp_add", "mcp_revoke", "mcp_who"):
        assert пункт not in имена, f"команда /{пункт} вернулась в меню бота"


async def test_спрятанных_команд_у_бота_нет(domain_env: object) -> None:
    """Каждая команда бота названа хотя бы в одном меню.

    Иначе о ней знает только тот, кто читал код: команда, забытая в меню, —
    ровно та скрытая функция, из-за которой показ записанного жил за кнопкой
    «Завершить» (T139). Список правится руками, и в этом весь смысл: решение
    «кому показывать» принимается, а не забывается.

    Исключение одно и названо: `/stops` — счётчик отказов мастера только
    админам (#436). Меню одно на всех (D448), и пункт, отвечающий аудиторам
    отказом, в нём не стоит; админ набирает команду сам.
    """
    имена = {name for name, _ in MENU_COMMANDS}

    assert имена == {
        "start",
        "records",
        "undo",
        "finish",
        # Сменить пиццерию начатой проверки (D628).
        "unit",
        "help",
        # Временная: обкатка формата отчёта (#261, D122) — уйдёт вместе с ней.
        "resend",
        "version",
        # Язык бота (D303) — у всех: выбрать его вправе каждый.
        "lang",
    }, "состав меню разошёлся с командами бота"


async def test_меню_называет_пункты_словами_владельца(domain_env: object) -> None:
    """Названия названы владельцем (D087), поэтому проверяются, а не подразумеваются."""
    bot, session = make_bot()

    await announce_commands(bot)

    объявления = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    описания = [c.description for объявлено in объявления for c in объявлено.commands]
    assert "Новая проверка" in описания, "пункт «Новая проверка» в меню не назван"
    assert "Установка MCP" not in описания, "пункт «Установка MCP» вернулся в меню (D626)"


async def test_снятия_сданной_проверки_в_меню_нет() -> None:
    """Решение D086: снимает проверку управляющая компания через MCP, не аудитор.

    Проверяется не текст, а состав меню: вход, которого у бота нет, не должен
    появиться «за компанию» при следующем пополнении списка.
    """
    имена = [name for name, _ in MENU_COMMANDS]
    for запрещённое in ("retract", "delete", "remove", "drop"):
        assert запрещённое not in имена, f"в меню появилось снятие проверки: /{запрещённое}"
