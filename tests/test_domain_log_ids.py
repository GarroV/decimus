"""Метка идентификатора в журнале (F-015): сам номер, код или логин в строку не попадают."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.types import Chat, Message, TelegramObject, User
from bot_harness import make_bot

from src.bot.access import AccessMiddleware, BindingCache
from src.db.bot_links import NEVER_BOUND
from src.domain.log_ids import TAG_LEN, log_id

STRANGER_ID = 770_123_456


def test_tag_has_fixed_format() -> None:
    tag = log_id(STRANGER_ID)
    assert tag.startswith("id:")
    assert len(tag) == len("id:") + TAG_LEN
    assert all(c in "0123456789abcdef" for c in tag[3:])


def test_same_value_gives_same_tag_for_int_and_str() -> None:
    assert log_id(STRANGER_ID) == log_id(STRANGER_ID)
    assert log_id(STRANGER_ID) == log_id(str(STRANGER_ID))


def test_different_values_give_different_tags() -> None:
    assert log_id(STRANGER_ID) != log_id(STRANGER_ID + 1)
    assert log_id("anna") != log_id("anne")


def test_raw_value_is_not_in_the_tag() -> None:
    for raw in (STRANGER_ID, "anna@example.com", "HQ"):
        assert str(raw) not in log_id(raw)


def test_none_is_written_as_absent() -> None:
    assert log_id(None) == "id:-"


@pytest.mark.asyncio
async def test_rejected_stranger_warning_has_no_raw_telegram_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot, _session = make_bot()
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=STRANGER_ID, type="private"),
        from_user=User(id=STRANGER_ID, is_bot=False, first_name="Т"),
        text="привет",
    ).as_(bot)
    mw = AccessMiddleware(frozenset(), BindingCache(standing=lambda _tg: NEVER_BOUND), None)

    async def handler(_e: TelegramObject, _data: dict[str, Any]) -> None:
        raise AssertionError("посторонний дошёл до обработчика")

    with caplog.at_level("WARNING", logger="src.bot.access"):
        await mw(handler, message, {})

    строки = [r.getMessage() for r in caplog.records if "постороннего" in r.getMessage()]
    assert строки, "отказ постороннему не записан в журнал"
    assert str(STRANGER_ID) not in строки[0]
    assert log_id(STRANGER_ID) in строки[0]
