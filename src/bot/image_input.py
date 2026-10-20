"""Кадр, присланный файлом, а не фото (#1023).

Телеграм сжимает «фото», но iPhone шлёт HEIC без сжатия, а JPEG/PNG аудитор
нередко присылает «как файл» — такое приходит документом, и хендлеры на
`F.photo` его не видели. Здесь один вход для таких документов: проверить, что это
картинка, скачать, привести к JPEG и отдать идентификатор файла — дальше кадр
идёт тем же путём, что и обычное фото.

Приведение к JPEG сидит и в `photos.fetch_bytes` (`image_convert.jpeg_if_image`):
идентификатор у документа остаётся телеграмовским, а разбор, отчёт и копии
качают его тем же вызовом, что и сжатое фото. Для настоящих фото (всегда JPEG)
это проход без перекодирования.
"""

from __future__ import annotations

from pathlib import PurePath

from aiogram.types import Document, Message

from .image_convert import normalize_image
from .photos import fetch_bytes
from .texts import t

#: Файлы свыше этого размера телеграм ботам не отдаёт (getFile).
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

#: Расширения, по которым документ без `image/*` в mime всё же считаем картинкой:
#: клиенты нередко шлют HEIC как `application/octet-stream`.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")


def looks_like_image(document: Document) -> bool:
    """Предварительный отбор по mime и имени; окончательно решает сигнатура байт."""
    if (document.mime_type or "").startswith("image/"):
        return True
    return PurePath(document.file_name or "").suffix.lower() in IMAGE_EXTENSIONS


async def document_frame_id(message: Message, lang: str) -> str | None:
    """`file_id` документа-картинки или `None` — тогда аудитору уже ответили.

    Не картинка, слишком большой, не скачался, битый — каждому случаю свой
    короткий ответ: промолчать на присланное нельзя.
    """
    document = message.document
    if document is None:
        return None
    if not looks_like_image(document):
        await message.answer(t("image.not_image", lang))
        return None
    if document.file_size is not None and document.file_size > MAX_DOCUMENT_BYTES:
        await message.answer(t("image.too_big", lang))
        return None
    bot = message.bot
    raw = None if bot is None else await fetch_bytes(bot, document.file_id)
    if raw is None:
        await message.answer(t("image.not_downloaded", lang))
        return None
    if len(raw) > MAX_DOCUMENT_BYTES:
        await message.answer(t("image.too_big", lang))
        return None
    if normalize_image(raw) is None:
        await message.answer(t("image.broken", lang))
        return None
    return document.file_id
