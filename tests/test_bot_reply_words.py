"""D254: класс и пометка повтора правятся ответом словами, а не кнопками.

Кнопки «Класс» и «Повтор ×2» из-под записи сняты. Их замена — короткий ответ
на сообщение о записи: «класс D2», «не повтор». Такой ответ о пункте не говорит
ничего, и отправь его в разбор, модель получила бы два слова без записи и
вернула бы не то. Поэтому он узнаётся целиком, а фраза, где есть что-то ещё,
уходит в разбор как раньше.
"""

from __future__ import annotations

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    bot_message,
    candidate,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    suggestion,
    text_message,
)
from bot_harness import callback_query as callback

from src import domain
from src.bot import repeats, reply_words
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.domain import get_state, start_inspection

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")


@pytest.mark.parametrize(
    ("фраза", "класс"),
    [
        ("класс D2", "D2"),
        ("D2", "D2"),
        ("д2", "D2"),
        ("Это D1.", "D1"),
        ("class d3", "D3"),
        ("класс D2, потому что просрочка", None),
        ("D0", None),
        ("грязная печь D2", None),
    ],
)
def test_класс_узнаётся_только_целым_ответом(фраза: str, класс: str | None) -> None:
    assert reply_words.spoken_level(фраза) == класс


@pytest.mark.parametrize(
    ("фраза", "пометка"),
    [
        ("не повтор", False),
        ("Это не повтор", False),
        ("not a repeat", False),
        ("повтор", True),
        ("это повтор", True),
        ("повтор ×2", True),
        ("повтор был в прошлый раз, но устранён", None),
    ],
)
def test_пометка_повтора_узнаётся_только_целым_ответом(фраза: str, пометка: bool | None) -> None:
    assert reply_words.repeat_mark(фраза) is пометка


@pytest.mark.parametrize(
    ("фраза", "ответ"),
    [("да", True), ("Yes", True), ("нет.", False), ("no", False), ("наверное", None)],
)
def test_да_нет(фраза: str, ответ: bool | None) -> None:
    assert reply_words.yes_no(фраза) is ответ


def _запись() -> domain.Finding:
    состояние = get_state(CHAT_ID)
    assert состояние is not None and len(состояние.findings) == 1
    return состояние.findings[0]


@pytest.mark.asyncio
async def test_класс_ответом_на_запись_меняет_класс(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    # Прошлой проверки нет — вопроса о повторе не будет, показ записи последний.
    monkeypatch.setattr(repeats, "seen_before", lambda *a, **k: None)
    stub_classify(monkeypatch, suggestion(candidate("PRD01", "D1", "hot_kitchen", "Заготовка")))
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    await feed(dp, bot, photo_message("frame-1", caption="заготовка, посмотри что тут"))
    await feed(dp, bot, callback("rec:pick:0"))
    показ = session.last_sent_id

    await feed(dp, bot, text_message("класс D2", reply_to=bot_message(показ)))

    запись = _запись()
    assert (запись.code, запись.level) == ("PRD01", "D2"), "класс не сменился ответом"
