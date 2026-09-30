"""Правка текста записи ответом словами (#454, решения D294, D295).

До #454 ответ «не ранч, а терияки» уходил в разбор с нуля: модель не видела
исходной записи и заводила новую формулировку, а то и другой пункт. Теперь
дешёвая модель по записи и словам решает, правка это текста или другое
нарушение (`src/recognize/revise.py`, подменена здесь).

Что защищает этот файл.

**Правка текста меняет только текст ТОЙ записи.** Пункт, класс, зона и номер
прежние, соседние записи не тронуты, разбор заново не зовётся.

**Другое нарушение идёт прежним путём** — разбором заново (D081).

**Отказ модели записи не меняет и в разбор не уходит.** Иначе вместо правки
молча завелась бы другая запись (D295), а аудитор узнал бы об этом из отчёта.
"""

from __future__ import annotations

from typing import Any

import pytest
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    bot_message,
    feed,
    make_bot,
    photo_message,
    stub_classify,
    stub_revise,
    suggestion,
    text_message,
)

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.texts import t
from src.domain import Finding, get_state, start_inspection
from src.recognize.errors import ModelUnavailable
from src.recognize.revise import Revision

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", allowed_ids=frozenset({AUDITOR_ID}), mode="polling")

#: Однозначная фраза на синтетической карте: CLN05, класс D1, зона — горячий цех.
OVEN = "печь грязная"
SINK_REPLY = "посудный участок, раковина и смеситель грязные"
FURNITURE = "тепловой участок, мебель участка в пятнах"
REVISED = "Печь и вытяжка в загрязнениях"


def started() -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")


def findings() -> list[Finding]:
    state = get_state(CHAT_ID)
    return [] if state is None else list(state.findings)


def spy_analyze(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Разбор заново — подменён пустышкой, чтобы видеть, звали ли его."""
    calls: list[dict[str, Any]] = []

    async def fake(*args: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr("src.bot.routers.correct.analyze", fake)
    return calls


async def two_records(dp: object, bot: object, session: object) -> int:
    """Две записи; вернуть номер сообщения бота о первой."""
    await feed(dp, bot, photo_message("frame-oven", caption=OVEN))  # type: ignore[arg-type]
    first: int = session.last_sent_id  # type: ignore[attr-defined]
    await feed(dp, bot, photo_message("frame-mebel", caption=FURNITURE))  # type: ignore[arg-type]
    return first


async def test_правка_текста_меняет_только_текст_той_записи(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    started()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    said = await two_records(dp, bot, session)
    before = {f.n: f for f in findings()}
    revise = stub_revise(monkeypatch, Revision(kind="wording", text=REVISED))
    analyzed = spy_analyze(monkeypatch)

    await feed(dp, bot, text_message("и вытяжка тоже", reply_to=bot_message(said)))

    after = {f.n: f for f in findings()}
    assert after.keys() == before.keys(), "правка завела или сняла запись"
    assert after[1].text == REVISED, "текст записи не поправлен"
    assert (after[1].code, after[1].level, after[1].zone) == (
        before[1].code,
        before[1].level,
        before[1].zone,
    ), "правка текста тронула пункт, класс или зону"
    assert after[2] == before[2], "тронута соседняя запись"
    assert analyzed == [], "правка текста ушла в разбор заново"
    assert session.last_text == t("correct.revised", "ru", n=1, text=REVISED)
    asked = revise[0]
    assert asked["item_code"] == before[1].code
    assert asked["wording"] == before[1].text, "модель не получила текущую формулировку"
    assert asked["words"] == "и вытяжка тоже"
    assert asked["lang"] == "ru"


async def test_ответ_на_подтверждение_правит_ту_же_запись(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Снова не то — ответьте на это сообщение» обязано работать."""
    started()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    said = await two_records(dp, bot, session)
    stub_revise(monkeypatch, Revision(kind="wording", text=REVISED))
    await feed(dp, bot, text_message("и вытяжка тоже", reply_to=bot_message(said)))
    confirmed = session.last_sent_id
    stub_revise(monkeypatch, Revision(kind="wording", text="Печь в загрязнениях"))

    await feed(dp, bot, text_message("вытяжка чистая", reply_to=bot_message(confirmed)))

    assert {f.n: f.text for f in findings()}[1] == "Печь в загрязнениях"


async def test_другое_нарушение_разбирается_заново(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    started()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    said = await two_records(dp, bot, session)
    revise = stub_revise(monkeypatch, Revision(kind="other", text=""))

    await feed(dp, bot, text_message(SINK_REPLY, reply_to=bot_message(said)))

    assert len(revise) == 1
    got = {f.n: (f.code, f.zone) for f in findings()}
    assert got[1] == ("CLN02", "dishwashing"), "другое нарушение не пошло в разбор заново"


async def test_отказ_модели_запись_не_меняет_и_в_разбор_не_уходит(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    started()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    said = await two_records(dp, bot, session)
    before = findings()
    stub_revise(monkeypatch, ModelUnavailable("провайдер молчит"))
    analyzed = spy_analyze(monkeypatch)

    await feed(dp, bot, text_message("не печь, а плита", reply_to=bot_message(said)))

    assert findings() == before, "отказ модели изменил записи"
    assert analyzed == [], "после отказа ответ ушёл в разбор — завелась бы другая запись"
    assert session.last_text == t("correct.revise_failed", "ru", n=1)


async def test_короткий_ответ_модель_правки_не_зовёт(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«класс D2» узнаётся целиком (D254) — платить модели за него незачем."""
    started()
    stub_classify(monkeypatch, suggestion())
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)
    said = await two_records(dp, bot, session)
    revise = stub_revise(monkeypatch, Revision(kind="wording", text="не должно быть"))

    await feed(dp, bot, text_message("не повтор", reply_to=bot_message(said)))

    assert revise == []
