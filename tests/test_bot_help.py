"""Краткая справка «как работать с ботом» (#257).

Справки у продукта не было вовсе: порядок работы знал тот, кому его рассказали
голосом, а бот на вопрос «как этим пользоваться» не отвечал ничем. Здесь
проверяется не текст дословно — он будет правиться, — а четыре свойства, без
которых справка бесполезна или вредна.

**Она видна.** Команда объявлена в меню телеграма: тот же урок, что у показа
записанного (T139) — команда, о которой не знаешь, спрятана независимо от того,
работает она или нет.

**Она говорит на языке аудитора**, а не стенда: проверку ведут на выбранном
языке, и русская простыня на английском стенде была бы ровно тем, против чего
заведён T131.

**Она доступна всегда** — и до начала проверки, и посреди неё. Справка, которую
нельзя прочитать, стоя посреди обхода, не нужна.

**Она не встревает в разговор.** Информационная часть (T158) ждёт обычный текст
и записывает его ответом на вопрос; команда обязана пройти мимо этого, а не
стать ответом «/help» в отчёте партнёру.
"""

from __future__ import annotations

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot, text_message

from src.bot.app import announce_commands, build_dispatcher
from src.bot.config import BotSettings
from src.bot.routers.help import HELP_COMMAND
from src.bot.texts import TEXTS, UI_LANGS, t
from src.domain import add_finding, get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Имя команды строкой: аудитор набирает и читает именно её, и переименование
#: обязано ломать тест, а не тихо переехать вместе с константой.
COMMAND = "/help"

#: Команды, названные в справке. Назвать несуществующую — хуже, чем промолчать:
#: человек набирает её на точке и получает молчание.
НАЗВАННЫЕ_КОМАНДЫ = ("/start", "/records", "/undo", "/finish", "/version")


async def test_команда_отвечает_справкой() -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message(COMMAND))

    assert session.texts == [t("help.text", "ru")], session.texts


async def test_справка_доступна_посреди_проверки(domain_env: object) -> None:
    """Вход не заперт состоянием: справку читают на точке, а не до выезда."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "PRD01", "D1", "fridge", "Ярлык без даты вскрытия")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message(COMMAND))

    assert session.texts == [t("help.text", "ru")], session.texts
    # Проверка не тронута: справка ничего не начинает и не завершает.
    состояние = get_state(CHAT_ID)
    assert состояние is not None and len(состояние.findings) == 1


async def test_язык_справки_это_язык_проверки(domain_env: object) -> None:
    """Язык интерфейса берётся из проверки — как у всего остального разговора."""
    # Язык мастера ложится во все три поля проверки (`routers/start.py`);
    # справке нужен именно язык ИНТЕРФЕЙСА, поэтому он назван явно.
    start_inspection(CHAT_ID, "Belgrade 2", "planned", "en", ui_lang="en", speech_lang="en")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message(COMMAND))

    assert session.texts == [t("help.text", "en")], session.texts


async def test_команда_объявлена_в_меню() -> None:
    bot, session = make_bot()

    await announce_commands(bot)

    объявлено = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    assert объявлено, "команды в меню не объявлены вовсе"
    пункты = {c.command: c.description for c in объявлено[0].commands}
    assert HELP_COMMAND in пункты, "справки в меню нет — её никто не найдёт"
    assert пункты[HELP_COMMAND] == t("cmd.help", "ru")
    for обязательная in ("start", "records", "undo", "finish"):
        assert обязательная in пункты, f"команда {обязательная} пропала из меню"


@pytest.mark.parametrize("lang", UI_LANGS)
def test_справка_заведена_на_обоих_языках(lang: str) -> None:
    текст = TEXTS["help.text"][lang]
    assert текст.strip(), f"справка не заведена на «{lang}»"
    # Подставляемых параметров у справки нет: появись фигурная скобка — и
    # каталог отдаст её как есть либо откажет, в зависимости от вызова.
    assert "{" not in текст and "}" not in текст


@pytest.mark.parametrize("lang", UI_LANGS)
def test_названы_только_существующие_команды(lang: str) -> None:
    """Каждая команда из справки объявлена в меню — и наоборот, кроме круга MCP."""
    from src.bot.app import MENU_COMMANDS

    в_меню = {f"/{name}" for name, _ in MENU_COMMANDS}
    текст = TEXTS["help.text"][lang]
    названные = {c for c in НАЗВАННЫЕ_КОМАНДЫ if c in текст}
    assert названные == set(НАЗВАННЫЕ_КОМАНДЫ), f"справка ({lang}) назвала не все команды"
    лишние = названные - в_меню
    assert лишние == set(), f"справка ({lang}) называет то, чего в меню нет: {лишние}"


@pytest.mark.parametrize("lang", UI_LANGS)
def test_справка_влезает_в_одно_сообщение(lang: str) -> None:
    """Предел телеграма — 4096 знаков; разрезанная надвое справка теряет смысл."""
    assert len(TEXTS["help.text"][lang]) <= 4096


async def test_справка_не_становится_ответом_в_информационной_части(domain_env: object) -> None:
    """Команда проходит мимо вопроса, а не записывается ответом на него (T158).

    Информационная часть ждёт обычный текст и записывает его без подтверждения
    (D064). Попади туда «/help» — партнёр прочитал бы это в отчёте, а аудитор
    узнал бы об этом от партнёра.
    """
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар на подине печи")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, text_message("/finish"))
    await feed(dp, bot, callback_query("fin:build"))

    await feed(dp, bot, text_message(COMMAND))

    assert t("help.text", "ru") in session.texts, "справка в информационной части не пришла"
    записанное = {
        code: (v["text"] if isinstance(v, dict) else v)
        for code, v in (get_state(CHAT_ID).info or {}).items()
    }
    assert записанное == {}, f"команда записалась ответом на вопрос: {записанное}"
