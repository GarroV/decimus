"""Immutable derived translations and letter drafts, scoped to their inspection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .config import check_environment
from .errors import DbError
from .pool import connection
from .reach import Reach, require_reach


@contextmanager
def _connect() -> Iterator[Any]:
    try:
        with connection(check_environment().dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise DbError("Не удалось подготовить языковую версию документа") from exc


def load(
    inspection_id: str, *, lang: str, kind: str, fingerprint: str, reach: Reach
) -> dict[str, Any] | None:
    """Read only within the caller's tenant and country scope."""
    with _connect() as conn:
        row = conn.execute(
            "select c.payload from inspection_document_cache c "
            "join inspections i on i.id=c.inspection_id join units u on u.id=i.unit_id "
            "where c.inspection_id=%(id)s and c.lang=%(lang)s and c.kind=%(kind)s "
            "and c.fingerprint=%(fingerprint)s "
            "and (%(tenants)s::text[] is null or i.tenant_code=any(%(tenants)s)) "
            "and (%(countries)s::text[] is null or u.country=any(%(countries)s))",
            dict(
                id=inspection_id,
                lang=lang,
                kind=kind,
                fingerprint=fingerprint,
                **require_reach(reach).params(),
            ),
        ).fetchone()
    return dict(row[0]) if row else None


def save(
    inspection_id: str,
    *,
    lang: str,
    kind: str,
    fingerprint: str,
    payload: dict[str, Any],
    reach: Reach,
) -> None:
    """Append a derived version without modifying the auditor's source or sent letters."""
    with _connect() as conn:
        found = conn.execute(
            "insert into inspection_document_cache (inspection_id,lang,kind,fingerprint,payload) "
            "select i.id,%(lang)s,%(kind)s,%(fingerprint)s,%(payload)s "
            "from inspections i join units u on u.id=i.unit_id where i.id=%(id)s "
            "and (%(tenants)s::text[] is null or i.tenant_code=any(%(tenants)s)) "
            "and (%(countries)s::text[] is null or u.country=any(%(countries)s)) "
            "on conflict do nothing returning inspection_id",
            dict(
                id=inspection_id,
                lang=lang,
                kind=kind,
                fingerprint=fingerprint,
                payload=Jsonb(payload),
                **require_reach(reach).params(),
            ),
        ).fetchone()
        if (
            found is None
            and load(inspection_id, lang=lang, kind=kind, fingerprint=fingerprint, reach=reach)
            is None
        ):
            raise DbError("Проверка недоступна для подготовки документов")
        conn.commit()
