"""Кадры записей загруженного черновика: список с размерами, снятие одного и всех (D627, #1206).

Добавлять кадры умели давно (`import_add_photo`, `import_upload_photos`,
`local_attach_photos`), снимать — нет: Mersin-4 лёг с 51 миниатюрой 420×560, и
заменить их оригиналами было нечем. Здесь три вещи:

- `frames_by_finding` — кадры каждой записи с размером копии и пометкой
  `low_resolution`, для `import_get_inspection`. Размер читается из самой копии в
  хранилище (в базе его нет), поэтому только в полном чтении, не в коротких
  ответах правок.
- `import_remove_photo` / `import_clear_photos` — снятие. Путь тот же, что у снятия
  кадра на вычитке в вебе (D465): `db.review_edit.detach_photo` — строка уходит
  транзакцией под замком черновика своего пространства, потом из хранилища уходят
  оригинал и превью. Свой путь удаления не заводится.

Кадр без копии (`shown` пуст: убран или не выгружен) списку не виден и по номеру не
снимается; об их числе ответ говорит отдельно, а не молчит.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, UnidentifiedImageError

from ..db.errors import ConfigError as DbConfigError
from ..db.errors import DbError, ReviseError
from .checklist_layout import Store
from .errors import ToolError
from .imports import _check_n, _db, _only_import, _photo_storage, _short_view
from .photo_quality import is_low_resolution
from .tools import _require_inspection_id

logger = logging.getLogger(__name__)

#: Параллельных чтений копий при подсчёте размеров: кадров бывает полсотни.
SIZE_READERS = 8


def _shots(inspection_id: str, *, tenant: str) -> dict[str, tuple[tuple[str, ...], int]]:
    """Запись → (id кадров с копией по порядку, число кадров без копии)."""
    from ..db import previews
    from ..db.reach import own_reach

    по_записям = previews.finding_previews(inspection_id, reach=own_reach(tenant))
    return {k: (v.shown, v.missing) for k, v in по_записям.items()}


def _size_of(
    inspection_id: str, photo_id: str, *, tenant: str, storage: object
) -> tuple[int, int] | None:
    """Ширина и высота копии кадра из хранилища; не прочиталась — `None`, а не выдумка."""
    from ..db import previews
    from ..db.reach import own_reach

    try:
        data = previews.preview_bytes(
            inspection_id,
            photo_id,
            reach=own_reach(tenant),
            storage=storage,  # type: ignore[arg-type]
        )
        if data is None:
            return None
        with Image.open(io.BytesIO(data)) as картинка:
            return картинка.size
    except (DbError, UnidentifiedImageError, OSError) as exc:
        logger.warning("размер кадра %s не прочитан: %r", photo_id, exc)
        return None


def frames_by_finding(
    inspection_id: str, *, tenant: str
) -> dict[str, list[dict[str, object]]] | None:
    """Кадры каждой записи: id для вызовов, номер по порядку, размер и `low_resolution`.

    `None` — база кадры не отдала: поле тогда не показывается, а не врёт пустотой.
    Размер неизвестен (копию не прочли или хранилище не настроено) — поля размера
    и `low_resolution` пусты, кадр всё равно в списке: снять его можно и так.
    """
    try:
        по_записям = _shots(inspection_id, tenant=tenant)
    except DbError:
        logger.warning("кадры черновика %s не прочитаны", inspection_id)
        return None
    пары = [(f, p) for f, (ids, _) in по_записям.items() for p in ids]
    try:
        хранилище: object | None = _photo_storage()
    except DbConfigError:
        хранилище = None
    if хранилище is None or not пары:
        размеры: list[tuple[int, int] | None] = [None] * len(пары)
    else:
        with ThreadPoolExecutor(max_workers=SIZE_READERS) as pool:
            размеры = list(
                pool.map(
                    lambda fp: _size_of(inspection_id, fp[1], tenant=tenant, storage=хранилище),
                    пары,
                )
            )
    итог: dict[str, list[dict[str, object]]] = {}
    for (запись, кадр), размер in zip(пары, размеры, strict=True):
        список = итог.setdefault(запись, [])
        список.append(
            {
                "photo": кадр,
                "frame": len(список) + 1,
                "width": размер[0] if размер else None,
                "height": размер[1] if размер else None,
                "low_resolution": is_low_resolution(*размер) if размер else None,
            }
        )
    return итог


def _draft_finding(
    inspection_id: str, n: int, *, tenant: str
) -> tuple[str, str, tuple[str, ...], int]:
    """Запись `n` черновика своего пространства: (id проверки, id записи, кадры, без копии)."""
    ident = _require_inspection_id(inspection_id)
    detail, _ = _only_import(ident, tenant=tenant)
    if not detail.inspection.on_review:
        raise ToolError(f"Проверка {ident} уже подтверждена — кадры у неё не снимаются")
    номер = _check_n(n)
    запись = next((f for f in detail.findings if f.n == номер), None)
    if запись is None:
        raise ToolError(f"В черновике нет записи #{номер}")
    with _db():
        ids, без_копии = _shots(ident, tenant=tenant).get(запись.id, ((), 0))
    return ident, запись.id, ids, без_копии


def _detach(ident: str, photos: Sequence[str], *, tenant: str) -> list[str]:
    """Снять кадры тем же путём, что вычитка в вебе. Первый отказ — `ToolError`."""
    from ..db import review_edit

    try:
        хранилище = _photo_storage()
    except DbConfigError:
        raise ToolError(
            "Хранилище кадров на этом стенде не настроено (S3_*). Кадры не сняты"
        ) from None
    снятые: list[str] = []
    for кадр in photos:
        try:
            with _db():
                review_edit.detach_photo(ident, кадр, tenant=tenant, storage=хранилище)
        except ReviseError as exc:
            есть = f"; уже снято кадров: {len(снятые)}" if снятые else ""
            raise ToolError(f"{exc}{есть}") from exc
        снятые.append(кадр)
    return снятые


def import_remove_photo(
    *, tenant: str, store: Store, actor: str, inspection_id: str, n: int, photo: str
) -> dict[str, object]:
    """Снять один кадр с записи `n` черновика загрузки (D627)."""
    del store, actor
    ident, _, ids, _ = _draft_finding(inspection_id, n, tenant=tenant)
    кадр = _require_inspection_id(photo)
    if кадр not in ids:
        raise ToolError(
            f"У записи #{n} нет такого кадра. Кадры записи (поле frames) показывает "
            f"import_get_inspection"
        )
    _detach(ident, [кадр], tenant=tenant)
    return _short_view(ident, tenant=tenant, note=f"photo removed from finding #{n}", n=n)


def import_clear_photos(
    *, tenant: str, store: Store, actor: str, inspection_id: str, n: int
) -> dict[str, object]:
    """Снять все кадры записи `n` черновика загрузки (D627)."""
    del store, actor
    ident, _, ids, без_копии = _draft_finding(inspection_id, n, tenant=tenant)
    снятые = _detach(ident, ids, tenant=tenant)
    ответ = _short_view(
        ident, tenant=tenant, note=f"{len(снятые)} photos removed from finding #{n}", n=n
    )
    if без_копии:
        ответ["warnings"] = [
            f"{без_копии} frame(s) of this finding have no stored copy and were not removed"
        ]
    return ответ
