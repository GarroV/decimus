"""Файлы проведённой работы и комментарии к принятой проверке: неизменяемая история."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .action_plans import clean_file_name
from .config import load_storage_settings
from .errors import StorageError
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
       e.file_name, e.size_bytes, e.storage_path, e.sha256
from inspection_followup e join inspections i on i.id = e.inspection_id
join units u on u.id = i.unit_id
where i.id = %(inspection)s
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(before)s::uuid is null or (e.created_at, e.id) < (
      select b.created_at, b.id from inspection_followup b
      where b.id = %(before)s and b.inspection_id = i.id))
order by e.created_at desc, e.id desc limit %(limit)s
"""

_FILE_SQL = """
select e.id, e.author, e.author_tenant, e.created_at, e.body,
       e.file_name, e.size_bytes, e.storage_path, e.sha256
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
        str(row[0]), row[1], row[2], row[3].astimezone(UTC), row[4], row[5], row[6], row[7], row[8]
    )


def list_entries(
    inspection_id: str, *, reach: Reach, before: str | None = None, as_admin: bool = False
) -> Page:
    """Последние 50 записей, с продолжением в прошлое без потери старых материалов."""
    params = _params(inspection_id, reach)
    params.update(before=str(uuid.UUID(before)) if before else None, limit=PAGE_SIZE + 1)
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
) -> str:
    """Добавить комментарий и/или исходный файл; при отказе записи убрать новый объект."""
    body = body.strip()
    author = author.strip()
    if not author or len(author) > 200 or len(body) > MAX_BODY or (not body and data is None):
        raise FollowupRefused("empty")
    if data is not None and (not data or len(data) > max_bytes):
        raise FollowupRefused("file")
    _check_head(inspection_id, reach)
    ident = str(uuid.uuid4())
    key = f"inspection-followup/{uuid.UUID(inspection_id)}/{ident}"
    store = storage
    uri = None
    if data is not None:
        store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
        uri = store.put(key, data, content_type="application/octet-stream")
    try:
        with reading("сохранить материалы проверки") as conn:
            # Повторная проверка; блокировку со снятием держит триггер базы.
            row = conn.execute(_HEAD_SQL, _params(inspection_id, reach)).fetchone()
            if row is None or row[0] != "finalized" or row[1] is not None:
                raise FollowupRefused("inspection")
            conn.execute(
                """insert into inspection_followup
                   (id, inspection_id, author_tenant, author, body,
                    storage_path, file_name, size_bytes, sha256)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
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
                ),
            )
            conn.commit()
    except Exception:
        if uri is not None and store is not None:
            try:
                store.delete(key)
            except StorageError:
                log.error("Не удалён непривязанный файл работы по проверке: %s", key)
        raise
    return ident
