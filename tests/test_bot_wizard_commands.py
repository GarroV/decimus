"""Команда меню в мастере начала проверки не становится названием точки (T250, #203).

Мастер ждал название пиццерии обычным текстом, а роутер `start` стоит в
диспетчере первым — поэтому команда, набранная или выбранная в меню на этом
шаге, до своего обработчика не доходила: она уезжала в название точки, а оттуда
в шапку отчёта и в имя файла. Касалось это всех пунктов меню одинаково.

**Что выбрано из трёх возможных поведений** (issue #203 их перечисляет):
команда выполняется, а мастер остаётся ждать название. Порядок роутеров при
этом не трогается — он в этом блоке несущий (см. комментарии в `app.py`), —
потому что мастер пропускает команду дальше сам (`SkipHandler`). Ровно так же
и по той же причине уже сделан вопрос о новой формулировке
(`routers/edit.py`): кадр и команда вместо ответа не съедаются, а идут своей
дорогой.

Отказ «название со слэша не принимается» отвергнут: пункт меню — это не
опечатка человека, а нажатие, и отвечать на него отказом значило бы заставить
аудитора доходить мастер до конца ради разовой настройки.
"""

from __future__ import annotations

import pytest
from aiogram import Bot, Dispatcher
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    RecordingSession,
    callback_query,
    feed,
    make_bot,
    photo_message,
    text_message,
)

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.bot.routers.mcp import MCP_COMMAND
from src.bot.routers.records import RECORDS_COMMAND
from src.bot.routers.version import VERSION_COMMAND
from src.bot.texts import t
from src.bot.version import build_version
from src.domain import get_state

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Пункты меню, которые видит каждый аудитор. `/start` сюда не входит: у него
#: в мастере свой смысл — он и раньше работал, потому что зарегистрирован в том
#: же роутере раньше вопроса о названии.
MENU = [RECORDS_COMMAND, "undo", "finish", VERSION_COMMAND]


async def ask_unit(settings: BotSettings = SETTINGS) -> tuple[Dispatcher, Bot, RecordingSession]:
    """Довести мастер до вопроса «как называется пиццерия?»."""
    bot, session = make_bot()
    dp = build_dispatcher(settings)
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    assert session.last_text == t("start.ask_unit", "ru")
    session.clear()
    return dp, bot, session


@pytest.mark.parametrize("command", MENU)
async def test_пункт_меню_не_становится_названием(domain_env: object, command: str) -> None:
    """Главный случай issue #203: бот принимал команду за название и шёл дальше."""
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message(f"/{command}"))

    assert t("start.ask_kind", "ru") not in session.texts, (
        f"/{command} принят названием пиццерии — мастер ушёл к виду проверки"
    )


async def test_команда_в_мастере_выполняется(domain_env: object) -> None:
    """Выбранный пункт меню обязан сработать, а не упереться в мастер."""
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message(f"/{VERSION_COMMAND}"))

    assert t("version.answer", "ru", v=build_version()) in session.texts


async def test_мастер_после_команды_ждёт_название_дальше(domain_env: object) -> None:
    """Команда не выбивает из мастера: следом присланное название принимается."""
    dp, bot, _session = await ask_unit()

    await feed(dp, bot, text_message(f"/{VERSION_COMMAND}"))
    await feed(dp, bot, text_message("Белград 2"))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))

    state = get_state(CHAT_ID)
    assert state is not None and state.unit == "Белград 2", (
        "мастер после команды название не принял"
    )


async def test_аудитор_понимает_почему_название_не_принято(domain_env: object) -> None:
    """Молчание здесь читалось бы как «бот проглотил название»."""
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message(f"/{VERSION_COMMAND}"))

    assert t("start.unit_command", "ru") in session.texts


async def test_незнакомая_команда_названием_тоже_не_становится(domain_env: object) -> None:
    """Опечатка в команде — не название точки, и не молчание в ответ.

    Своего обработчика у неё нет, поэтому сказать о ней может только мастер:
    промолчи он — аудитор решит, что название принято.
    """
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message("/recordz"))

    assert t("start.ask_kind", "ru") not in session.texts
    assert t("start.unit_command", "ru") in session.texts


async def test_название_с_командой_внутри_принимается(domain_env: object) -> None:
    """Слэш ловится только в начале: «Дом 5/1» — законное название точки."""
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message("Белград, Дом 5/1"))

    assert session.last_text == t("start.ask_kind", "ru")


async def test_кадр_вместо_названия_отвечает_как_раньше(domain_env: object) -> None:
    """Правка не должна была тронуть остальные ответы мастера."""
    dp, bot, session = await ask_unit()

    await feed(dp, bot, photo_message("frame"))

    assert session.last_text == t("start.unit_expected", "ru")


async def test_start_в_мастере_работает_как_прежде(domain_env: object) -> None:
    """`/start` — единственный выход из тупика, и мастер его не перехватывает."""
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message("/start"))

    assert t("start.unit_command", "ru") not in session.texts, (
        "`/start` в мастере получил отговорку вместо приветствия"
    )
    assert session.last_text == t("start.greeting", "ru")


async def test_установка_mcp_в_мастере_работает_и_мастер_ждёт_дальше(domain_env: object) -> None:
    """Прогон из issue #203 целиком: пункт меню, с которого дефект и заметили.

    До T250 бот отвечал «Вид проверки?» — то есть принимал `/mcp` названием
    пиццерии и шёл дальше, а дальше это название уезжало в шапку отчёта.
    """
    dp, bot, session = await ask_unit()

    await feed(dp, bot, text_message(f"/{MCP_COMMAND}"))

    assert t("start.ask_kind", "ru") not in session.texts, (
        "«Установка MCP» принята названием пиццерии"
    )
    # Круг доступа на этом стенде не назначен, и заслон пункта отвечает именно
    # так. Ответ взят его — то есть команда дошла до своего обработчика, а не
    # осталась в мастере; что печатает пункт с назначенным кругом, проверяет
    # `tests/test_bot_mcp_setup.py`, и повторять это здесь нечем.
    assert t("mcp.circle_unset", "ru") in session.texts, "пункт меню до своего заслона не дошёл"

    await feed(dp, bot, text_message("Белград 2"))
    assert session.last_text == t("start.ask_kind", "ru"), (
        "мастер после пункта меню название не принял"
    )
