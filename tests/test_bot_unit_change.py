"""«Сменить пиццерию» посреди обхода (D628).

Аудитор завёл проверку не на ту точку. Записанное терять нельзя: меняется шапка,
записи и кадры остаются. Название сверяется со справочником, как на старте; пока бот
ждёт название, команда или кадр отменяют смену и не становятся названием.
"""

from __future__ import annotations

import pytest
from bot_harness import CHAT_ID, feed, make_bot, photo_message, text_message

from src.bot import unit_pick
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.routers import unit as unit_router
from src.domain import add_finding, get_state, start_inspection

pytestmark = pytest.mark.asyncio

SETTINGS = BotSettings(token="unused-in-tests", mode="polling", auditor_names={})


def _справочник(monkeypatch: pytest.MonkeyPatch, *, known: str | None) -> None:
    def сверка(typed: str, *_also: str, tenant: str) -> unit_pick.UnitMatch:
        return unit_pick.UnitMatch(name=known, suggestions=(), checked=True)

    monkeypatch.setattr(unit_router, "match_unit", сверка)


async def test_пиццерия_сменена_а_записи_на_месте(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    add_finding(CHAT_ID, "CLN05", "D1", "hot_kitchen", "Нагар на подине печи")
    _справочник(monkeypatch, known="Belgrade-3")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    # Act
    await feed(dp, bot, text_message("/unit"))
    спросил = session.last_text
    await feed(dp, bot, text_message("Белград 3"))

    # Assert
    assert "Белград 2" in спросил
    состояние = get_state(CHAT_ID)
    assert состояние is not None
    assert состояние.unit == "Belgrade-3"
    assert [f.code for f in состояние.findings] == ["CLN05"]
    assert "Belgrade-3" in session.last_text


async def test_незнакомая_пиццерия_не_ставится(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    _справочник(monkeypatch, known=None)
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message("/unit"))
    await feed(dp, bot, text_message("Белград 9"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.unit == "Белград 2"
    assert "нет в справочнике" in session.last_text


async def test_кадр_вместо_названия_отменяет_смену(
    domain_env: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    _справочник(monkeypatch, known="Belgrade-3")
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message("/unit"))
    await feed(dp, bot, photo_message("frame-1"))
    session.clear()
    # Текст после отмены — уже не название пиццерии.
    await feed(dp, bot, text_message("Белград 3"))

    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.unit == "Белград 2"


async def test_без_начатой_проверки_менять_нечего(domain_env: object) -> None:
    bot, session = make_bot()
    dp = build_dispatcher(SETTINGS)

    await feed(dp, bot, text_message("/unit"))

    assert "нет начатой проверки" in session.last_text
