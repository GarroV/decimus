"""Сжатая копия кадра для показа в админке (D219).

Владелец 28.09: «конечно сжатое, не в максимальном качестве, а в достаточном,
чтоб было видно». Оригинал живёт до вычитки (D202) или семь дней (D213), копия
— навсегда: по ней в карточке видно, что именно зафиксировано.

Размер выбран так, чтобы на экране ноутбука кадр во всю ширину карточки был
чётким, а на весь срок хранения это стоило сотни килобайт, а не мегабайты:
длинная сторона 1600 px, JPEG качества 75 — типичный кадр телефона ложится в
150–400 КБ.
"""

from __future__ import annotations

import io
from typing import Any, Protocol

import psycopg
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import check_environment, load_storage_settings
from .errors import DbError, StorageError
from .storage import S3PhotoStorage, key_of_uri

#: Длинная сторона копии в пикселях. Меньше — надпись на ценнике и дата на
#: маркировке перестают читаться; больше — копия приближается к оригиналу.
PREVIEW_MAX_SIDE = 1600

#: Качество JPEG копии. 75 — точка, где артефакты сжатия на фото кухни ещё не
#: видны глазом, а размер падает в разы относительно 90+.
PREVIEW_QUALITY = 75

PREVIEW_CONTENT_TYPE = "image/jpeg"


def make_preview(data: bytes) -> bytes:
    """Сжать кадр до копии для показа. Не картинка — `StorageError`, а не пустые байты.

    Поворот по EXIF применяется ДО сжатия: телефон пишет кадр боком и
    помечает, как его повернуть, а сохранённая без метки копия легла бы боком.
    """
    try:
        with Image.open(io.BytesIO(data)) as исходный:
            кадр = ImageOps.exif_transpose(исходный).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise StorageError(f"Кадр не читается как изображение ({type(exc).__name__})") from exc
    кадр.thumbnail((PREVIEW_MAX_SIDE, PREVIEW_MAX_SIDE), Image.Resampling.LANCZOS)
    выход = io.BytesIO()
    кадр.save(выход, format="JPEG", quality=PREVIEW_QUALITY, optimize=True, progressive=True)
    return выход.getvalue()


# ── Чтение для админки ─────────────────────────────────────────────────────
#
# Арендатор проверяется присоединением проверки: у `photos` своей колонки
# арендатора нет, и запрос без этого отдал бы кадр чужой управляющей компании
# по угаданному идентификатору. Убранные кадры (`purged_at`, D089) не
# показываются — их в хранилище уже нет.
_PREVIEWS_OF_INSPECTION_SQL = """
select p.finding_id, p.id
from photos p
join inspections i on i.id = p.inspection_id
where p.inspection_id = %(id)s and i.tenant_code = %(tenant)s
  and p.preview_path is not null and p.purged_at is null
order by p.created_at, p.id
"""

_PREVIEW_PATH_SQL = """
select p.preview_path
from photos p
join inspections i on i.id = p.inspection_id
where p.id = %(photo)s and p.inspection_id = %(id)s and i.tenant_code = %(tenant)s
  and p.preview_path is not null and p.purged_at is null
"""


def _read(sql: str, params: dict[str, str]) -> list[tuple[Any, ...]]:
    settings = check_environment()
    try:
        with psycopg.connect(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except psycopg.Error as exc:
        raise DbError(f"Не удалось прочитать кадры проверки ({type(exc).__name__})") from exc


def finding_previews(inspection_id: str, *, tenant: str) -> dict[str, tuple[str, ...]]:
    """Кадры со сжатой копией по записям: идентификатор записи → кадры по порядку."""
    по_записям: dict[str, list[str]] = {}
    for finding_id, photo_id in _read(
        _PREVIEWS_OF_INSPECTION_SQL, {"id": inspection_id, "tenant": tenant}
    ):
        по_записям.setdefault(str(finding_id), []).append(str(photo_id))
    return {запись: tuple(кадры) for запись, кадры in по_записям.items()}


def preview_bytes(
    inspection_id: str, photo_id: str, *, tenant: str, storage: PreviewReader | None = None
) -> bytes | None:
    """Сжатая копия кадра этой проверки этого арендатора — или `None`, если её нет."""
    строки = _read(_PREVIEW_PATH_SQL, {"id": inspection_id, "photo": photo_id, "tenant": tenant})
    if not строки:
        return None
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
    data = store.get(key_of_uri(str(строки[0][0])))
    if not data:
        raise StorageError(f"Хранилище отдало пустой объект вместо копии кадра {photo_id}")
    return data


class PreviewReader(Protocol):
    """Чтение объекта из хранилища — всё, что нужно показу копии."""

    def get(self, key: str) -> bytes: ...
