"""Повторная отправка отчёта по завершённой проверке (#261, D122).

Функция временная: владелец обкатывает новую подачу отчёта на живых данных и
просил возможность получить его ещё раз. Проверяется здесь не текст документа,
а три свойства, без которых она опасна или бесполезна.

**Она ничего не пишет в историю.** Проверка уже слита в базу при завершении;
второй слив сделал бы из одного визита два. Это главное отличие от `/finish`.

**Она не трогает саму проверку.** Отчёт пересобирается, записи остаются как
были: правка записанной проверки запрещена решением проекта, и «прислать ещё
раз» не должно оказаться лазейкой к ней.

**Её видно и она говорит на языке аудитора** — тем же правилом, что и справка
(T131): команда, о которой не знаешь, спрятана, а русская подпись на
английском стенде противоречит языку проверки.
"""

from __future__ import annotations

import pytest
from bot_harness import AUDITOR_ID, CHAT_ID, feed, make_bot, text_message

from src.bot.app import announce_commands, build_dispatcher
from src.bot.config import BotSettings
from src.bot.routers.resend import RESEND_COMMAND
from src.bot.texts import TEXTS, UI_LANGS, t
from src.domain import add_finding, get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Имя команды строкой: аудитор набирает именно её.
COMMAND = "/resend"


async def test_без_проверки_говорит_что_присылать_нечего(domain_env: object) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message(COMMAND))

    assert session.texts == [t("resend.no_inspection", "ru")], session.texts


async def test_проверка_остаётся_нетронутой(domain_env: object) -> None:
    """Пересборка отчёта — чтение: записи после неё те же, что были."""
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "PRD01", "D1", "fridge", "Ярлык без даты вскрытия")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message(COMMAND))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and len(состояние.findings) == 1
    assert состояние.findings[0].code == "PRD01"
    assert состояние.findings[0].zone == "fridge"


async def test_команда_объявлена_в_меню() -> None:
    bot, session = make_bot()

    await announce_commands(bot)

    объявлено = [c for c in session.calls if type(c).__name__ == "SetMyCommands"]
    assert объявлено, "команды в меню не объявлены вовсе"
    пункты = {c.command: c.description for c in объявлено[0].commands}
    assert RESEND_COMMAND in пункты, "повторной отправки в меню нет — её никто не найдёт"
    assert пункты[RESEND_COMMAND] == t("cmd.resend", "ru")


@pytest.mark.parametrize("lang", UI_LANGS)
@pytest.mark.parametrize(
    "ключ", ("cmd.resend", "resend.no_inspection", "resend.building", "resend.caption", "resend.failed")
)
def test_тексты_заведены_на_обоих_языках(ключ: str, lang: str) -> None:
    текст = TEXTS[ключ][lang]
    assert текст.strip(), f"«{ключ}» не заведён на «{lang}»"
