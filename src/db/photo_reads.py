"""Кадры проверки для вычитки на приёмке (D199).

Кадры живут только до вычитки (D202): смотрят их на экране приёмки, и
только выгруженные и не убранные. Кадр ещё не выгружен — его нет в выдаче, а
не «пустая картинка»: у телеграмного идентификатора снаружи не открыть ничего.
"""

from __future__ import annotations

import re

from .config import load_storage_settings
from .errors import StorageError
from .queries import _reading, _require_inspection_id, _require_tenant
from .storage import PhotoStorage, S3PhotoStorage

_STORAGE_URI = re.compile(r"^s3://(?P<bucket>[^/]+)/(?P<key>.+)$")

# Арендатор сверяется в самом запросе: кадр чужой проверки не существует для
# того, кто его просит, тем же ответом, что несуществующий.
_PHOTOS_OF_INSPECTION_SQL = """
select p.id, p.finding_id
from photos p
join inspections i on i.id = p.inspection_id
where p.inspection_id = %(id)s and i.tenant_code = %(tenant)s
  and p.finding_id is not null
  and p.storage_path is not null and p.purged_at is null
order by p.id
"""

_PHOTO_PATH_SQL = """
select p.storage_path
from photos p
join inspections i on i.id = p.inspection_id
where p.id = %(photo)s and p.inspection_id = %(id)s and i.tenant_code = %(tenant)s
  and p.storage_path is not null and p.purged_at is null
"""


def photos_by_finding(inspection_id: str, *, tenant: str) -> dict[str, tuple[str, ...]]:
    """`{идентификатор записи: (идентификаторы кадров, …)}` — только выгруженные."""
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    кадры: dict[str, list[str]] = {}
    with _reading("кадры проверки") as conn, conn.cursor() as cur:
        cur.execute(_PHOTOS_OF_INSPECTION_SQL, {"id": ident, "tenant": tenant_code})
        for photo_id, finding_id in cur.fetchall():
            кадры.setdefault(str(finding_id), []).append(str(photo_id))
    return {запись: tuple(ids) for запись, ids in кадры.items()}


def read_photo(
    inspection_id: str, photo_id: str, *, tenant: str, storage: PhotoStorage | None = None
) -> bytes | None:
    """Байты кадра. `None` — кадра нет, он чужой, не выгружен или уже убран.

    Отказ хранилища — `StorageError`: «кадр есть, но не читается» и «кадра
    нет» разные ответы.
    """
    ident = _require_inspection_id(inspection_id)
    photo = _require_inspection_id(photo_id)
    tenant_code = _require_tenant(tenant)
    with _reading("кадр проверки") as conn, conn.cursor() as cur:
        cur.execute(_PHOTO_PATH_SQL, {"photo": photo, "id": ident, "tenant": tenant_code})
        row = cur.fetchone()
    if row is None:
        return None
    разбор = _STORAGE_URI.match(str(row[0]))
    if разбор is None:
        raise StorageError(f"Ссылка кадра {photo} записана не в виде s3://корзина/ключ")
    store = storage if storage is not None else S3PhotoStorage(load_storage_settings())
    return store.get(разбор.group("key"))
