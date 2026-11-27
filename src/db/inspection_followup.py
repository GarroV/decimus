"""Файлы проведённой работы и комментарии к принятой проверке: неизменяемая история."""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from PIL import Image, UnidentifiedImageError

from . import inspection_remediation
from .action_plans import clean_file_name
from .config import load_storage_settings
from .errors import StorageError
from .previews import make_preview
from .reach import Reach, require_reach
from .reading import reading
from .storage import PhotoStorage, S3PhotoStorage

log = logging.getLogger(__name__)
PAGE_SIZE = 50
MAX_BODY = 5000


class FollowupRefused(ValueError):
    """Материал не принят: пустая запись, недоступная или ещё не принятая проверка."""


@dataclass(frozen=True)
class Entry:
    id: str
    author: str
    author_tenant: str
    created_at: datetime
    body: str
    file_name: str | None
    size_bytes: int | None
    storage_path: str | None
    sha256: str | None
    finding_id: str | None = None
    preview_path: str | None = None


@dataclass(frozen=True)
class Page:
    entries: tuple[Entry, ...] = ()
    more: bool = False


_HEAD_SQL = """
select i.status, i.retracted_at
from inspections i join units u on u.id = i.unit_id
where i.id = %(inspection)s
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""

_LIST_SQL = """
select e.id, e.author, e.author_tenant, e.created_at, e.body,
       e.file_name, e.size_bytes, e.storage_path, e.sha256, e.finding_id, e.preview_path
from inspection_followup e join inspections i on i.id = e.inspection_id
join units u on u.id = i.unit_id
where i.id = %(inspection)s
  and e.finding_id is not distinct from %(finding)s::uuid
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(before)s::uuid is null or (e.created_at, e.id) < (
      select b.created_at, b.id from inspection_followup b
      where b.id = %(before)s and b.inspection_id = i.id))
order by e.created_at desc, e.id desc limit %(limit)s
"""

_FILE_SQL = """
select e.id, e.author, e.author_tenant, e.created_at, e.body,
       e.file_name, e.size_bytes, e.storage_path, e.sha256, e.finding_id, e.preview_path
from inspection_followup e join inspections i on i.id = e.inspection_id
join units u on u.id = i.unit_id
where i.id = %(inspection)s and e.id = %(entry)s and e.storage_path is not null
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""


def _params(inspection_id: str, reach: Reach) -> dict[str, Any]:
    return {**require_reach(reach).params(), "inspection": str(uuid.UUID(inspection_id))}


def _entry(row: tuple[Any, ...]) -> Entry:
    return Entry(
        str(row[0]),
        row[1],
        row[2],
        row[3].astimezone(UTC),
        row[4],
        row[5],
        row[6],
        row[7],
        row[8],
        str(row[9]) if row[9] else None,
        row[10],
    )


def list_entries(
    inspection_id: str,
    *,
    reach: Reach,
    before: str | None = None,
    as_admin: bool = False,
    finding_id: str | None = None,
) -> Page:
    """Последние 50 записей, с продолжением в прошлое без потери старых материалов."""
    params = _params(inspection_id, reach)
    params.update(
        before=str(uuid.UUID(before)) if before else None,
        limit=PAGE_SIZE + 1,
        finding=str(uuid.UUID(finding_id)) if finding_id else None,
    )
    with reading("материалы проверки", as_admin=as_admin) as conn:
        rows = conn.execute(_LIST_SQL, params).fetchall()
    return Page(tuple(_entry(row) for row in rows[:PAGE_SIZE]), len(rows) > PAGE_SIZE)


def get_file(
    inspection_id: str, entry_id: str, *, reach: Reach, as_admin: bool = False
) -> Entry | None:
    """Метаданные вложения только внутри охвата проверки, включая политики базы."""
    params = {**_params(inspection_id, reach), "entry": str(uuid.UUID(entry_id))}
    with reading("файл работы по проверке", as_admin=as_admin) as conn:
        row = conn.execute(_FILE_SQL, params).fetchone()
    return _entry(row) if row else None


def _check_head(inspection_id: str, reach: Reach) -> None:
    with reading("проверка для материалов") as conn:
        row = conn.execute(_HEAD_SQL, _params(inspection_id, reach)).fetchone()
        if row is None or row[0] != "finalized" or row[1] is not None:
            raise FollowupRefused("inspection")


def append(
    inspection_id: str,
    *,
    reach: Reach,
    author: str,
    body: str,
    file_name: str = "",
    data: bytes | None = None,
    max_bytes: int,
    storage: PhotoStorage | None = None,
    finding_id: str | None = None,
) -> str:
    """Добавить комментарий и/или исходный файл; при отказе записи убрать новый объект."""
    body = body.strip()
    author = author.strip()
    if not author or len(author) > 200 or len(body) > MAX_BODY or (not body and data is None):
        raise FollowupRefused("empty")
    if data is not None and (not data or len(data) > max_bytes):
        raise FollowupRefused("file")
    _check_head(inspection_id, reach)
    if finding_id:
        try:
            finding_id = str(uuid.UUID(finding_id))
            inspection_remediation.check_item(inspection_id, finding_id, reach=reach)
        except (ValueError, inspection_remediation.RemediationRefused) as exc:
            raise FollowupRefused("item") from exc
    ident = str(uuid.uuid4())
    key = f"inspection-followup/{uuid.UUID(inspection_id)}/{ident}"
    store = storage
    uri = preview_uri = None
    uploaded: list[str] = []
    try:
        if data is not None:
            store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
            uri = store.put(key, data, content_type="application/octet-stream")
            uploaded.append(key)
            preview = _optional_preview(data) if finding_id else None
            if preview is not None:
                preview_key = key + "/preview.jpg"
                preview_uri = store.put(preview_key, preview, content_type="image/jpeg")
                uploaded.append(preview_key)
        with reading("сохранить материалы проверки") as conn:
            # Повторная проверка; блокировку со снятием держит триггер базы.
            row = conn.execute(_HEAD_SQL, _params(inspection_id, reach)).fetchone()
            if row is None or row[0] != "finalized" or row[1] is not None:
                raise FollowupRefused("inspection")
            conn.execute(
                """insert into inspection_followup
                   (id, inspection_id, author_tenant, author, body,
                    storage_path, file_name, size_bytes, sha256, finding_id, preview_path)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    ident,
                    inspection_id,
                    reach.tenant,
                    author,
                    body,
                    uri,
                    clean_file_name(file_name)[:200] if data is not None else None,
                    len(data) if data is not None else None,
                    hashlib.sha256(data).hexdigest() if data is not None else None,
                    finding_id,
                    preview_uri,
                ),
            )
            conn.commit()
    except Exception:
        if store is not None:
            for uploaded_key in uploaded:
                try:
                    store.delete(uploaded_key)
                except StorageError:
                    log.error("Не удалён непривязанный файл работы по проверке: %s", uploaded_key)
        raise
    return ident


def _optional_preview(data: bytes) -> bytes | None:
    """Безопасная JPEG-копия фото; исходный документ всегда остаётся скачиваемым."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 25_000_000:
                    return None
            return make_preview(data)
    except (
        StorageError,
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return None
