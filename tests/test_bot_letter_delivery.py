"""Полное письмо доезжает до аудитора и за пределами лимита сообщения Telegram."""

from __future__ import annotations

import pytest
from aiogram.types import BufferedInputFile
from bot_harness import make_bot, text_message

from src.bot.routers import finish
from src.bot.texts import t

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("lang", ["ru", "en"])
async def test_short_letter_keeps_the_existing_message(lang: str) -> None:
    bot, session = make_bot()
    letter = "Полный текст письма — пример с Unicode 🧀."

    await finish.deliver_letter(text_message("trigger").as_(bot), letter, lang)

    assert session.texts == [t("finish.letter", lang, letter=letter)]
    assert not session.documents


@pytest.mark.parametrize(
    "letter",
    ["Замечание: проверка ёмкости 🧀.\n" * 500, "🧀" * 2050, "x" * 4096],
    ids=["long-cyrillic", "emoji-utf16-overflow", "wrapper-overflow"],
)
async def test_long_letter_is_delivered_as_complete_utf8_file(letter: str) -> None:
    bot, session = make_bot()

    await finish.deliver_letter(text_message("trigger").as_(bot), letter, "ru")

    assert not session.texts, "Не отправлять обрезанную копию длинного письма сообщением"
    assert len(session.documents) == 1
    document = session.documents[0]
    assert isinstance(document.document, BufferedInputFile)
    assert document.document.data == letter.encode("utf-8")
    assert document.document.filename == "letter.txt"
    assert document.caption == t("finish.letter_file", "ru")


async def test_message_at_safe_limit_keeps_the_existing_path() -> None:
    bot, session = make_bot()
    prefix = t("finish.letter", "ru", letter="")
    letter = "я" * (4096 - len(prefix.encode("utf-16-le")) // 2)

    await finish.deliver_letter(text_message("trigger").as_(bot), letter, "ru")

    assert session.texts == [prefix + letter]
    assert not session.documents
