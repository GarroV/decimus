"""Файл и обсуждение принятой проверки: история, исходные байты и изоляция стран."""

from __future__ import annotations

import io
from pathlib import Path

import psycopg
import pytest
from conftest import requires_db
from db_harness import привязать_страну, точка_справочника
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import inspection_followup as store
from src.db.accept import accept_inspection
from src.db.errors import DbError
from src.db.push import push_inspection
from src.db.reach import reach_of
from src.db.space import acting_space
from src.domain import start_inspection
from src.web import inspection_followup as web

pytestmark = requires_db
ORIGIN = {"Origin": "http://localhost"}


class Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes, *, content_type: str) -> str:
        self.objects[key] = data
        return f"s3://test/{key}"

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


def test_file_discussion_history_and_country_boundary(
    pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from db_harness import set_retraction_env

    set_retraction_env(db_env, monkeypatch)
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    start_inspection(9_240_501, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    inspection = push_inspection(9_240_501)
    accept_inspection(inspection, tenant="HQ", actor="owner")
    disk = Storage()
    for module in (store, web):
        monkeypatch.setattr(module, "S3PhotoStorage", lambda _settings: disk)
        monkeypatch.setattr(module, "load_storage_settings", lambda: None)

    def client(tenant: str, role: str = "admin") -> FlaskClient:
        подменить_двери(monkeypatch, tenant=tenant, role=role)
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        result = собрать(tenant=tenant).test_client()
        assert войти(result).status_code == 302
        return result

    url = f"/inspections/{inspection}/work?lang=ru"
    hq = client("HQ")
    data = b"%PDF-1.7 action plan original bytes\x00\xff"
    result = hq.post(
        url, data={"file": (io.BytesIO(data), "План.pdf"), "body": "Что сделано"}, headers=ORIGIN
    )
    assert result.status_code == 303, result.text
    assert result.location.endswith("#inspection-work")
    with acting_space("HQ"):
        page = store.list_entries(inspection, reach=reach_of("HQ"))
    assert len(page.entries) == 1
    entry = page.entries[0]
    file_url = f"/inspections/{inspection}/work/{entry.id}/file"
    download = hq.get(file_url)
    assert download.status_code == 200 and download.data == data
    assert download.headers["Content-Disposition"].startswith("attachment;")
    assert download.headers["Cache-Control"] == "private, no-store"
    assert "Работа по проверке" in hq.get(f"/inspections/{inspection}").text

    ge = client("GE")
    assert (
        ge.post(
            url, data={"body": "<script>alert(1)</script>\nРаботы завершены"}, headers=ORIGIN
        ).status_code
        == 303
    )
    html = ge.get(f"/inspections/{inspection}").text
    assert "&lt;script&gt;" in html and "<script>alert(1)</script>" not in html
    assert ge.get(file_url).data == data
    assert (
        ge.post(
            url, data={"file": (io.BytesIO(b"new version"), "План.pdf")}, headers=ORIGIN
        ).status_code
        == 303
    )
    assert ge.get(file_url).data == data  # Исходный файл не заменён новой версией.
    assert len(disk.objects) == 2
    assert ge.post(url, data={}, headers=ORIGIN).status_code == 400
    assert (
        ge.post(url, data={"file": (io.BytesIO(b""), "empty.pdf")}, headers=ORIGIN).status_code
        == 400
    )
    assert ge.post(url, data={"body": "test"}).status_code == 403
    panel = ge.post(url, data={"body": "Уточнение в панели"}, headers={**ORIGIN, "X-Panel": "1"})
    assert panel.status_code == 200 and 'class="spanel' in panel.text
    assert "Уточнение в панели" in panel.text

    am = client("AM")
    assert am.get(file_url).status_code == 404
    assert am.post(url, data={"body": "foreign"}, headers=ORIGIN).status_code == 404
    assert len(disk.objects) == 2
    guest = client("HQ", "guest")
    assert guest.get(file_url).data == data
    assert guest.post(url, data={"body": "guest"}, headers=ORIGIN).status_code == 403

    # Ограничение есть в самой базе: прямой SQL роли приложения чужое не читает,
    # историю нельзя переписать или стереть.
    with acting_space("AM"):
        assert store.list_entries(inspection, reach=reach_of("HQ")).entries == ()
    with psycopg.connect(db_env) as conn:
        conn.execute("select set_config('decimus.space', 'HQ', false)")
        for sql in (
            "update inspection_followup set body = 'changed'",
            "delete from inspection_followup",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with conn.transaction():
                    conn.execute(sql)

    # Подмена содержимого в хранилище не выдаётся человеку как исходный файл.
    hq = client("HQ")
    disk.objects[entry.storage_path.removeprefix("s3://test/")] = b"corrupt"
    assert hq.get(file_url).status_code == 503
    monkeypatch.setattr(store, "PAGE_SIZE", 2)
    with acting_space("HQ"):
        reach = reach_of("HQ")
        first = store.list_entries(inspection, reach=reach)
        older = store.list_entries(inspection, reach=reach, before=first.entries[-1].id)
        assert first.more and len(first.entries) == len(older.entries) == 2
        assert {e.id for e in first.entries}.isdisjoint(e.id for e in older.entries)
        assert entry.id in {e.id for e in older.entries}


def test_refuses_draft_and_compensates_storage_failure(
    pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from db_harness import set_retraction_env

    set_retraction_env(db_env, monkeypatch)
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    start_inspection(9_240_502, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    inspection = push_inspection(9_240_502)
    disk = Storage()
    with acting_space("HQ"):
        reach = reach_of("HQ")
        with pytest.raises(store.FollowupRefused, match="inspection"):
            store.append(
                inspection,
                reach=reach,
                author="owner",
                body="",
                data=b"x",
                max_bytes=1,
                storage=disk,
            )
        assert disk.objects == {}
        accept_inspection(inspection, tenant="HQ", actor="owner")
        with pytest.raises(store.FollowupRefused, match="file"):
            store.append(
                inspection,
                reach=reach,
                author="owner",
                body="",
                data=b"xx",
                max_bytes=1,
                storage=disk,
            )
        assert disk.objects == {}
        # Политика не разрешает автора чужого пространства: объект убирается.
        from src.db.reach import Reach

        with pytest.raises(DbError):
            store.append(
                inspection,
                reach=Reach("GE", None, None),
                author="owner",
                body="",
                data=b"x",
                max_bytes=1,
                storage=disk,
            )
        assert disk.objects == {}
        store.append(inspection, reach=reach, author="owner", body="История работ", max_bytes=1)
        from src.db.retract import retract_inspection

        retract_inspection(inspection, tenant="HQ", reason="Проверка архива", storage=disk)
        assert store.list_entries(inspection, reach=reach).entries == ()
        archived = store.list_entries(inspection, reach=reach, as_admin=True)
        assert len(archived.entries) == 1 and archived.entries[0].body == "История работ"
        with pytest.raises(store.FollowupRefused, match="inspection"):
            store.append(inspection, reach=reach, author="owner", body="Поздно", max_bytes=1)
