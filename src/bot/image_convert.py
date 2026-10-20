"""Приведение присланной картинки к JPEG (#1023).

Чистые функции без телеграма: сигнатуры, поворот по EXIF, перекодирование. Нужны
и входу документов (`image_input`), и скачиванию (`photos.fetch_bytes`).
"""

from __future__ import annotations

import logging
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

logger = logging.getLogger(__name__)

register_heif_opener()

#: Бренды контейнера HEIF в байтах 8..12 файла (после длины и `ftyp`).
HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heif")

JPEG_QUALITY = 92


def is_heif(raw: bytes) -> bool:
    """Сигнатура HEIC/HEIF: `....ftyp<бренд>`."""
    return raw[4:8] == b"ftyp" and raw[8:12] in HEIF_BRANDS


def is_jpeg(raw: bytes) -> bool:
    return raw[:3] == b"\xff\xd8\xff"


def is_png(raw: bytes) -> bool:
    return raw[:8] == b"\x89PNG\r\n\x1a\n"


def is_webp(raw: bytes) -> bool:
    return raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"


def is_image(raw: bytes) -> bool:
    """Байты начинаются как картинка из тех, что принимает бот."""
    return is_jpeg(raw) or is_heif(raw) or is_png(raw) or is_webp(raw)


def _has_rotation(raw: bytes) -> bool:
    try:
        with Image.open(BytesIO(raw)) as img:
            return int(img.getexif().get(0x0112, 1)) != 1
    except (OSError, UnidentifiedImageError):
        return False


def normalize_image(raw: bytes) -> bytes | None:
    """Байты картинки в JPEG с учётом EXIF-ориентации. Не картинка — `None`.

    JPEG без поворота возвращается как есть: перекодировать каждое сжатое фото
    телеграма значило бы терять качество и время зря.
    """
    if not is_image(raw):
        return None
    if is_jpeg(raw) and not _has_rotation(raw):
        return raw
    try:
        with Image.open(BytesIO(raw)) as img:
            upright = ImageOps.exif_transpose(img)
            out = BytesIO()
            upright.convert("RGB").save(out, format="JPEG", quality=JPEG_QUALITY)
            return out.getvalue()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, ValueError):
        logger.warning("присланный файл не разобрался как картинка", exc_info=True)
        return None


def jpeg_if_image(raw: bytes) -> bytes:
    """Для скачивания: картинку — в JPEG, всё остальное (голос) — как есть."""
    if not is_image(raw):
        return raw
    return normalize_image(raw) or raw
