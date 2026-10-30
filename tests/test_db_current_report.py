"""Источники актуального PDF: неизменяемые версии и охват чтения кадров."""

from __future__ import annotations

import psycopg
from conftest import requires_db

from src.db import previews, reports
from src.db.reach import Reach
from src.db.space import acting_space

pytestmark = requires_db


class Store:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.objects[key] = data
        return f"s3://bucket/{key}"


def inspection(dsn: str) -> str:
    with psycopg.connect(dsn) as conn:
        uid = conn.execute(
            "insert into units (tenant_code, name, name_normalized, country) "
            "values ('HQ', 'PDF test', 'pdf test', 'RS') returning id"
        ).fetchone()[0]
        return str(
            conn.execute(
                "insert into inspections (tenant_code, unit_id, chat_id, kind, inspection_date, "
                "report_lang, ui_lang, speech_lang, checklist_version, pct, grade, "
                "source_fingerprint, status) values "
                "('HQ', %s, 1, 'planned', '2026-10-30', 'ru', 'ru', 'ru', 'test', "
                "100, 'A', 'pdf-test', 'draft') returning id",
                (uid,),
            ).fetchone()[0]
        )


def test_same_source_deduplicates_and_new_source_preserves_old_version(
    pg_dsn: str,
    db_env: str,
) -> None:
    ident, store = inspection(pg_dsn), Store()
    first = reports.upload_report(
        ident, data=b"%PDF-test", storage=store, source_fingerprint="a" * 64
    )
    same = reports.upload_report(
        ident, data=b"%PDF-test", storage=store, source_fingerprint="a" * 64
    )
    changed = reports.upload_report(
        ident, data=b"%PDF-test", storage=store, source_fingerprint="b" * 64
    )
    assert same.already
    assert same.storage_path == first.storage_path
    assert changed.storage_path != first.storage_path
    assert len(store.objects) == 2
    with psycopg.connect(pg_dsn) as conn:
        assert (
            conn.execute(
                "select count(*) from reports where inspection_id=%s", (ident,)
            ).fetchone()[0]
            == 2
        )


def test_photo_sources_include_info_photos_and_enforce_reach(
    pg_dsn: str,
    db_env: str,
) -> None:
    ident = inspection(pg_dsn)
    with psycopg.connect(pg_dsn) as conn:
        finding = conn.execute(
            "insert into findings (inspection_id,n,code,level,zone) "
            "values (%s,1,'PRD01','D1','fridge') returning id",
            (ident,),
        ).fetchone()[0]
        answer = conn.execute(
            "insert into inspection_info (inspection_id,position,code,text) "
            "values (%s,1,'INF03','Answer') returning id",
            (ident,),
        ).fetchone()[0]
        conn.execute(
            "insert into photos (inspection_id,finding_id,telegram_file_id,storage_path) "
            "values (%s,%s,'photo1','s3://bucket/finding')",
            (ident, finding),
        )
        conn.execute(
            "insert into photos (inspection_id,info_id,telegram_file_id,storage_path) "
            "values (%s,%s,'photo2','s3://bucket/info')",
            (ident, answer),
        )
    reach = Reach("HQ", None, None)
    sources = previews.report_photos(ident, reach=reach)
    assert len(sources) == 2
    assert {photo.finding_n for photo in sources} == {1, None}
    assert {photo.info_code for photo in sources} == {None, "INF03"}
    assert previews.report_photos(ident, reach=Reach("HQ", None, ("AZ",))) == ()
    with acting_space("no-access"):
        assert previews.report_photos(ident, reach=reach) == ()
