"""#1023: кадр, присланный файлом (HEIC с iPhone, «без сжатия»), идёт тем же путём, что фото.

До правки хендлеры слушали только `F.photo`, и документ не попадал никуда:
аудитор присылал снимок и не получал ответа. Здесь документ проходит через
настоящий диспетчер, а сессия отдаёт на скачивание настоящие байты.

Что защищается:

**Документ-картинка принимается как кадр** — JPEG и HEIC, ответ тот же, что на
фото («Кадр принят»); HEIC при скачивании становится JPEG, с учётом EXIF-поворота.

**Не картинка и битая картинка получают понятный ответ**, а не молчание и не
падение. Файл больше 20 МБ вежливо отклоняется до скачивания.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pytest
from aiogram import Bot
from aiogram.types import Chat, Document, Message
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    FAKE_TOKEN,
    RecordingSession,
    _user,
    feed,
    next_message_id,
)
from PIL import Image
from pillow_heif import register_heif_opener

from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.image_convert import is_heif, jpeg_if_image, normalize_image
from src.bot.image_input import MAX_DOCUMENT_BYTES
from src.bot.material import Material
from src.bot.photos import fetch_bytes
from src.bot.texts import t
from src.domain import start_inspection

SETTINGS = BotSettings(token="unused-in-tests", mode="polling")

register_heif_opener()


class _Session(RecordingSession):
    """Сессия, отдающая на скачивание заданные байты."""

    def __init__(self, content: bytes) -> None:
        super().__init__()
        self._content = content

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 — сигнатура из BaseSession
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        yield self._content


def _image_bytes(fmt: str, size: tuple[int, int] = (64, 32), exif_orientation: int = 1) -> bytes:
    img = Image.new("RGB", size, (200, 40, 40))
    exif = Image.Exif()
    exif[0x0112] = exif_orientation
    out = BytesIO()
    img.save(out, format=fmt, exif=exif)
    return out.getvalue()


def _document_message(
    file_id: str, *, mime: str | None, name: str = "IMG_0001", size: int | None = None
) -> Message:
    return Message(
        message_id=next_message_id(),
        date=datetime.now(tz=timezone.utc),
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=_user(AUDITOR_ID, "Владимир Гарро"),
        document=Document(
            file_id=file_id,
            file_unique_id=f"{file_id}-u",
            file_name=name,
            mime_type=mime,
            file_size=size,
        ),
    )


class _Caught:
    def __init__(self) -> None:
        self.materials: list[Material] = []

    async def __call__(self, message: object, material: Material, lang: str) -> None:
        self.materials.append(material)


async def _send(content: bytes, **document: Any) -> RecordingSession:
    start_inspection(CHAT_ID, "Белград 2", "planned", "ru")
    session = _Session(content)
    bot = Bot(token=FAKE_TOKEN, session=session)
    dp = build_dispatcher(SETTINGS, on_material=_Caught(), album_window=5.0)
    await feed(dp, bot, _document_message("doc-1", **document))
    return session


@pytest.mark.asyncio
async def test_jpeg_document_is_taken_as_a_frame(domain_env: object) -> None:
    session = await _send(_image_bytes("JPEG"), mime="image/jpeg", name="a.jpg")
    assert session.last_text == t("material.photo_taken", "ru")


@pytest.mark.asyncio
async def test_heic_document_is_taken_as_a_frame(domain_env: object) -> None:
    heic = _image_bytes("HEIF")
    assert is_heif(heic), "тест не получил настоящий HEIC"
    session = await _send(heic, mime="image/heic", name="IMG_0001.HEIC")
    assert session.last_text == t("material.photo_taken", "ru")


@pytest.mark.asyncio
async def test_pdf_document_is_refused(domain_env: object) -> None:
    session = await _send(b"%PDF-1.4 ...", mime="application/pdf", name="отчёт.pdf")
    assert session.last_text == t("image.not_image", "ru")


@pytest.mark.asyncio
async def test_broken_image_is_refused(domain_env: object) -> None:
    session = await _send(b"not an image at all", mime="image/jpeg", name="a.jpg")
    assert session.last_text == t("image.broken", "ru")


@pytest.mark.asyncio
async def test_oversized_document_is_refused_before_download(domain_env: object) -> None:
    session = await _send(b"", mime="image/heic", name="big.heic", size=MAX_DOCUMENT_BYTES + 1)
    assert session.last_text == t("image.too_big", "ru")
    assert not any(type(c).__name__ == "GetFile" for c in session.calls)


def test_texts_exist_in_both_languages() -> None:
    for key in ("image.not_image", "image.too_big", "image.broken", "image.not_downloaded"):
        assert t(key, "ru") != t(key, "en")


def test_rotated_jpeg_becomes_upright() -> None:
    # Ориентация 6: кадр хранится лёжа и при показе поворачивается на 90 градусов.
    # (У HEIC поворот снимает сам libheif при чтении, поэтому проверяем на JPEG.)
    raw = _image_bytes("JPEG", size=(64, 32), exif_orientation=6)
    out = normalize_image(raw)
    assert out is not None
    with Image.open(BytesIO(out)) as img:
        assert img.format == "JPEG"
        assert img.size == (32, 64)


def test_plain_jpeg_passes_untouched() -> None:
    raw = _image_bytes("JPEG")
    assert normalize_image(raw) == raw


def test_non_image_bytes_pass_through_download_helper() -> None:
    # Голос идёт через тот же `fetch_bytes`: трогать его нельзя.
    ogg = b"OggS\x00\x02voice"
    assert jpeg_if_image(ogg) == ogg


@pytest.mark.asyncio
async def test_fetch_bytes_returns_jpeg_for_heic(domain_env: object) -> None:
    bot = Bot(token=FAKE_TOKEN, session=_Session(_image_bytes("HEIF")))
    raw = await fetch_bytes(bot, "doc-1")
    assert raw is not None
    with Image.open(BytesIO(raw)) as img:
        assert img.format == "JPEG"
