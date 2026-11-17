"""A bounded backfill pass advances past missing frames without discarding them."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from conftest import requires_db
from test_photo_backfill import Склад, _проверка, _ссылки

from src.bot.photo_backfill import STALE_AFTER_SEC, STALE_BATCH, backfill_once
from src.db.photos import pending_photo_uploads

pytestmark = requires_db


def queued_frames(pg_dsn: str) -> str:
    inspection = _проверка(541, кадры=("missing-original",))
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update photos set created_at=now()-interval '5 days' where inspection_id=%s",
            (inspection,),
        )
        conn.execute(
            "insert into photos (finding_id,inspection_id,telegram_file_id,created_at) "
            "select p.finding_id,p.inspection_id,'missing-'||n, p.created_at "
            "from photos p cross join generate_series(1,200) n where p.inspection_id=%s",
            (inspection,),
        )
        conn.execute(
            "insert into photos (finding_id,inspection_id,telegram_file_id,created_at) "
            "select finding_id,inspection_id,'available-tail',now()-interval '4 days' "
            "from photos where inspection_id=%s limit 1",
            (inspection,),
        )
    return inspection


@pytest.mark.asyncio
async def test_more_than_two_hundred_missing_frames_cannot_starve_the_available_tail(
    domain_env: Path, db_env: str, pg_dsn: str
):
    inspection = queued_frames(pg_dsn)
    requested = []
    recovered = False

    async def fetch(file_id):
        requested.append(file_id)
        return b"synthetic frame bytes" if recovered or file_id == "available-tail" else None

    store = Склад()
    first = await backfill_once(
        fetch, min_age_sec=STALE_AFTER_SEC, max_age_sec=None, limit=STALE_BATCH, storage=store
    )
    assert first.pending == first.missing == STALE_BATCH
    assert first.uploaded == 0
    requested.clear()
    second = await backfill_once(
        fetch, min_age_sec=STALE_AFTER_SEC, max_age_sec=None, limit=STALE_BATCH, storage=store
    )
    assert second.pending == STALE_BATCH
    assert "available-tail" in requested
    assert second.uploaded == 1
    assert _ссылки(db_env, inspection)["available-tail"]
    assert sum(ref is None for ref in _ссылки(db_env, inspection).values()) == 201
    recovered = True
    for _ in range(2):
        await backfill_once(
            fetch, min_age_sec=STALE_AFTER_SEC, max_age_sec=None, limit=STALE_BATCH, storage=store
        )
    assert all(_ссылки(db_env, inspection).values())
    assert pending_photo_uploads(min_age_sec=0) == []


def test_claim_rotation_survives_worker_exit_and_skips_a_concurrent_lock(
    domain_env: Path, db_env: str, pg_dsn: str
):
    inspection = _проверка(542, кадры=("first-missing", "second-missing"))
    # Hold one row without consuming it: another worker must claim the other.
    with psycopg.connect(pg_dsn) as lock:
        locked = lock.execute(
            "select telegram_file_id from photos where inspection_id=%s "
            "order by created_at,id limit 1 for update",
            (inspection,),
        ).fetchone()[0]
        first = pending_photo_uploads(min_age_sec=0, limit=1)
        assert len(first) == 1 and len(first[0].file_ids) == 1
        assert locked not in first[0].file_ids
    # A crash after claim changed scheduling only; the unhandled bytes remain pending.
    second = pending_photo_uploads(min_age_sec=0, limit=1)
    assert second[0].file_ids == (locked,)
    third = pending_photo_uploads(min_age_sec=0, limit=1)
    assert third[0].file_ids == first[0].file_ids
    assert _ссылки(db_env, inspection) == {"first-missing": None, "second-missing": None}
