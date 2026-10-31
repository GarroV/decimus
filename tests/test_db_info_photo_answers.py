"""Photo-only info has owned evidence at commit; no caption is invented."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db

from src.db.push import push_inspection
from src.domain import set_info, start_inspection

psycopg = pytest.importorskip("psycopg")
pytestmark = requires_db


def pending(domain_env: Path, chat: int):
    start_inspection(
        chat, unit=f"Synthetic info photos {chat}", kind="planned", report_lang="ru", tenant="HQ"
    )
    set_info(chat, "INF08", "Synthetic historical caption")
    return push_inspection(chat)


def info_id(conn, inspection):
    return conn.execute(
        "select id from inspection_info where inspection_id=%s", (inspection,)
    ).fetchone()[0]


def test_deferred_photo_answer_accepts_captionless_packet_and_rejects_last_delete(
    domain_env: Path, db_env: str
):
    inspection = pending(domain_env, 793010701)
    with psycopg.connect(db_env, autocommit=True) as conn:
        owner = info_id(conn, inspection)
        with conn.transaction():
            conn.execute("update inspection_info set text='' where id=%s", (owner,))
            for ref in ("synthetic-a", "synthetic-b"):
                conn.execute(
                    "insert into photos(info_id,inspection_id,telegram_file_id) values(%s,%s,%s)",
                    (owner, inspection, ref),
                )
        assert conn.execute(
            "select text from inspection_info where id=%s", (owner,)
        ).fetchone() == ("",)
        with conn.transaction():
            conn.execute(
                "delete from photos where info_id=%s and telegram_file_id='synthetic-a'", (owner,)
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("delete from photos where info_id=%s", (owner,))
        assert conn.execute(
            "select count(*) from photos where info_id=%s", (owner,)
        ).fetchone() == (1,)
        with conn.transaction():
            conn.execute("update inspection_info set text='Caption added' where id=%s", (owner,))
            conn.execute("delete from photos where info_id=%s", (owner,))
        assert conn.execute(
            "select text from inspection_info where id=%s", (owner,)
        ).fetchone() == ("Caption added",)


def test_empty_update_and_insert_rollback_without_fabricated_answer(domain_env: Path, db_env: str):
    inspection = pending(domain_env, 793010702)
    with psycopg.connect(db_env, autocommit=True) as conn:
        owner = info_id(conn, inspection)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("update inspection_info set text='' where id=%s", (owner,))
        assert conn.execute(
            "select text from inspection_info where id=%s", (owner,)
        ).fetchone() == ("Synthetic historical caption",)
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "insert into inspection_info(inspection_id,position,code,text) "
                    "values(%s,1,'INF01','')",
                    (inspection,),
                )
        assert conn.execute(
            "select count(*) from inspection_info where inspection_id=%s", (inspection,)
        ).fetchone() == (1,)


def test_moving_last_photo_cannot_leave_blank_owner(domain_env: Path, db_env: str):
    inspection = pending(domain_env, 793010703)
    with psycopg.connect(db_env, autocommit=True) as conn:
        owner = info_id(conn, inspection)
        with conn.transaction():
            other = conn.execute(
                "insert into inspection_info(inspection_id,position,code,text) "
                "values(%s,1,'INF01','Other') returning id",
                (inspection,),
            ).fetchone()[0]
            conn.execute("update inspection_info set text='' where id=%s", (owner,))
            conn.execute(
                "insert into photos(info_id,inspection_id,telegram_file_id) "
                "values(%s,%s,'synthetic-owner')",
                (owner, inspection),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("update photos set info_id=%s where info_id=%s", (other, owner))
        assert conn.execute(
            "select info_id from photos where inspection_id=%s", (inspection,)
        ).fetchone() == (owner,)


def test_info_photo_cannot_reference_another_inspection(domain_env: Path, db_env: str):
    first = pending(domain_env, 793010704)
    second = pending(domain_env, 793010705)
    with psycopg.connect(db_env, autocommit=True) as conn:
        owner = info_id(conn, first)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    "insert into photos(info_id,inspection_id,telegram_file_id) "
                    "values(%s,%s,'synthetic-wrong-owner')",
                    (owner, second),
                )


def test_push_roundtrip_keeps_photo_only_packet_and_is_idempotent(
    domain_env: Path, db_env: str, monkeypatch: pytest.MonkeyPatch
):
    from dataclasses import replace

    from src.db.queries import get_inspection
    from src.db.reach import own_reach
    from src.domain import get_state
    from src.domain.models import InfoAnswer

    chat = 793010707
    start_inspection(
        chat, unit="Synthetic photo-only push", kind="planned", report_lang="ru", tenant="HQ"
    )
    snapshot = replace(get_state(chat), info={"INF08": InfoAnswer("INF08", "", ["ref-a", "ref-b"])})
    monkeypatch.setattr("src.db.push.get_state", lambda _: snapshot)
    inspection = push_inspection(chat)
    assert push_inspection(chat) == inspection
    detail = get_inspection(inspection, reach=own_reach("HQ"), include_on_review=True)
    assert detail is not None
    assert [(field.code, field.text) for field in detail.info] == [("INF08", "")]
    with psycopg.connect(db_env) as conn:
        assert conn.execute(
            "select count(*) from inspection_info where inspection_id=%s", (inspection,)
        ).fetchone() == (1,)
        assert conn.execute(
            "select telegram_file_id from photos where inspection_id=%s order by telegram_file_id",
            (inspection,),
        ).fetchall() == [("ref-a",), ("ref-b",)]


def test_two_transactions_cannot_each_delete_one_of_last_two_photos(domain_env: Path, db_env: str):
    inspection = pending(domain_env, 793010708)
    with psycopg.connect(db_env, autocommit=True) as setup:
        owner = info_id(setup, inspection)
        with setup.transaction():
            setup.execute("update inspection_info set text='' where id=%s", (owner,))
            for ref in ("concurrent-a", "concurrent-b"):
                setup.execute(
                    "insert into photos(info_id,inspection_id,telegram_file_id) values(%s,%s,%s)",
                    (owner, inspection, ref),
                )
    with psycopg.connect(db_env) as first, psycopg.connect(db_env) as second:
        first.execute("set local lock_timeout='5s'")
        second.execute("set local lock_timeout='5s'")
        first.execute(
            "delete from photos where info_id=%s and telegram_file_id='concurrent-a'", (owner,)
        )
        second.execute(
            "delete from photos where info_id=%s and telegram_file_id='concurrent-b'", (owner,)
        )
        first.commit()
        with pytest.raises(psycopg.errors.CheckViolation):
            second.commit()
        second.rollback()
    with psycopg.connect(db_env) as verify:
        assert verify.execute(
            "select telegram_file_id from photos where info_id=%s", (owner,)
        ).fetchall() == [("concurrent-b",)]
