"""Исправления принятой проверки: доказательства, приёмка, история и границы ролей."""

from __future__ import annotations

import io
from pathlib import Path

import psycopg
import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from PIL import Image
from test_inspection_followup_flow import ORIGIN, Storage
from web_harness import войти, подменить_двери, собрать

from src.db import inspection_followup as evidence
from src.db import inspection_remediation as store
from src.db.accept import accept_inspection
from src.db.push import push_inspection
from src.db.reach import reach_of
from src.db.space import acting_space
from src.domain import add_finding, start_inspection
from src.web import inspection_followup as web

pytestmark = requires_db


def test_corrections_evidence_review_history_and_roles(
    pg_dsn: str,
    db_env: str,
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_retraction_env(db_env, monkeypatch)
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    start_inspection(9_241_101, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    add_finding(9_241_101, code="PRD02", level="D2", zone="cold_kitchen", text="Образец нарушения")
    add_finding(9_241_101, code="PRD01", level="R", zone="fridge", text="Образец рекомендации")
    inspection = push_inspection(9_241_101)
    accept_inspection(inspection, tenant="HQ", actor="reviewer")
    with psycopg.connect(pg_dsn) as conn:
        finding = str(
            conn.execute(
                "select id from findings where inspection_id=%s and level='D2'", (inspection,)
            ).fetchone()[0]
        )
        assert conn.execute("select count(*) from inspection_remediation").fetchone()[0] == 0
    disk = Storage()
    for module in (evidence, web):
        monkeypatch.setattr(module, "S3PhotoStorage", lambda _settings: disk)
        monkeypatch.setattr(module, "load_storage_settings", lambda: None)

    def client(tenant: str, role: str = "admin"):
        подменить_двери(monkeypatch, tenant=tenant, role=role)
        monkeypatch.setattr("src.web.auth.reach_of", reach_of)
        result = собрать(tenant=tenant).test_client()
        assert войти(result).status_code == 302
        return result

    card = f"/inspections/{inspection}?repair={finding}"
    upload = f"/inspections/{inspection}/work"
    actions = f"/inspections/{inspection}/repairs/{finding}"
    partner = client("GE", "auditor")
    html = partner.get(card).text
    assert "Нужно исправить" in html and "Закрыто 0 из 1" in html
    assert "Подтвердить исправление и закрыть" not in html
    with psycopg.connect(pg_dsn) as conn:
        assert conn.execute("select count(*) from inspection_remediation").fetchone()[0] == 0
    image = io.BytesIO()
    Image.new("RGB", (80, 60), "blue").save(image, "PNG")
    original = image.getvalue()
    response = partner.post(
        upload,
        data={
            "repair": finding,
            "body": "Исправлено <b>сегодня</b>",
            "file": (io.BytesIO(original), "proof.png"),
        },
        headers=ORIGIN,
    )
    assert response.status_code == 303, response.text
    assert response.location.endswith("#repair-" + finding)
    with acting_space("GE"):
        state = store.states(inspection, reach=reach_of("GE"))[finding]
        assert (state.status, state.revision) == ("open", 1)
        page = evidence.list_entries(inspection, finding_id=finding, reach=reach_of("GE"))
        assert not evidence.list_entries(inspection, reach=reach_of("GE")).entries
    entry = page.entries[0]
    file_url = f"/inspections/{inspection}/work/{entry.id}/file"
    preview_url = f"/inspections/{inspection}/work/{entry.id}/preview"
    assert partner.get(file_url).data == original
    assert partner.get(preview_url).mimetype == "image/jpeg"
    assert "&lt;b&gt;сегодня&lt;/b&gt;" in partner.get(card).text
    assert (
        partner.post(actions + "/review/confirm", data={"revision": 1}, headers=ORIGIN).status_code
        == 403
    )
    assert (
        partner.post(
            actions + "/submit", data={"repair": finding, "revision": 1}, headers=ORIGIN
        ).status_code
        == 303
    )
    # Администратор партнёра не принимает исправления проверки УК.
    partner_admin = client("GE")
    assert (
        partner_admin.post(
            actions + "/review/confirm", data={"revision": 2}, headers=ORIGIN
        ).status_code
        == 403
    )
    hq = client("HQ")
    assert (
        hq.post(actions + "/review/return", data={"revision": 2}, headers=ORIGIN).status_code == 409
    )
    assert (
        hq.post(
            actions + "/review/return",
            data={"revision": 2, "reason": "Нужно уточнение"},
            headers=ORIGIN,
        ).status_code
        == 303
    )
    partner = client("GE", "auditor")
    assert (
        partner.post(
            upload, data={"repair": finding, "body": "Уточнение подтверждено"}, headers=ORIGIN
        ).status_code
        == 303
    )
    assert (
        partner.post(actions + "/submit", data={"revision": 4}, headers=ORIGIN).status_code == 303
    )
    # Новое подтверждение после открытия страницы делает старую версию непригодной для закрытия.
    assert (
        partner.post(
            upload, data={"repair": finding, "body": "Дополнительное подтверждение"}, headers=ORIGIN
        ).status_code
        == 303
    )
    hq = client("HQ")
    assert (
        hq.post(actions + "/review/confirm", data={"revision": 5}, headers=ORIGIN).status_code
        == 409
    )
    assert (
        hq.post(actions + "/review/confirm", data={"revision": 6}, headers=ORIGIN).status_code
        == 303
    )
    assert "Закрыто 1 из 1" in hq.get(card).text
    partner = client("GE", "auditor")
    before = dict(disk.objects)
    assert (
        partner.post(
            upload,
            data={"repair": finding, "file": (io.BytesIO(b"late"), "late.txt")},
            headers=ORIGIN,
        ).status_code
        == 400
    )
    assert disk.objects == before
    assert (
        partner.post(
            upload, data={"body": "Общий комментарий после закрытия"}, headers=ORIGIN
        ).status_code
        == 303
    )
    assert partner.get(file_url).data == original
    hq = client("HQ")
    assert (
        hq.post(
            actions + "/review/reopen",
            data={"revision": 7, "reason": "Повторная проверка"},
            headers=ORIGIN,
        ).status_code
        == 303
    )
    with acting_space("HQ"):
        history = store.events(inspection, finding, reach=reach_of("HQ"))
        assert [e.kind for e in reversed(history.entries)] == [
            "evidence",
            "submitted",
            "returned",
            "evidence",
            "submitted",
            "evidence",
            "confirmed",
            "reopened",
        ]
        assert history.entries[0].reason == "Повторная проверка"
    foreign = client("AM")
    assert foreign.get(card).status_code == 404
    assert foreign.get(file_url).status_code == 404
    assert foreign.get(preview_url).status_code == 404
    assert (
        foreign.post(
            upload, data={"repair": finding, "body": "foreign"}, headers=ORIGIN
        ).status_code
        == 404
    )
    guest = client("HQ", "guest")
    assert guest.get(card).status_code == 200
    assert (
        guest.post(upload, data={"repair": finding, "body": "guest"}, headers=ORIGIN).status_code
        == 403
    )


def test_partner_admin_reviews_internal_inspection(
    pg_dsn: str,
    db_env: str,
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_retraction_env(db_env, monkeypatch)
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")
    точка_справочника("Batumi-2", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    with acting_space("GE"):
        start_inspection(9_241_102, unit="Batumi-2", kind="planned", report_lang="ru", tenant="GE")
        add_finding(
            9_241_102, code="PRD02", level="D2", zone="cold_kitchen", text="Внутреннее замечание"
        )
        inspection = push_inspection(9_241_102)
        accept_inspection(inspection, tenant="GE", actor="partner reviewer")
        finding = next(iter(store.states(inspection, reach=reach_of("GE"))))
        evidence.append(
            inspection,
            reach=reach_of("GE"),
            author="employee",
            body="Подтверждение",
            finding_id=finding,
            max_bytes=100,
        )
        store.transition(
            inspection, finding, reach=reach_of("GE"), actor="employee", action="submit", revision=1
        )
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    monkeypatch.setattr("src.web.auth.reach_of", reach_of)
    client = собрать(tenant="GE").test_client()
    assert войти(client).status_code == 302
    response = client.post(
        f"/inspections/{inspection}/repairs/{finding}/review/confirm",
        data={"revision": 2},
        headers=ORIGIN,
    )
    assert response.status_code == 303, response.text
    with acting_space("GE"):
        assert store.states(inspection, reach=reach_of("GE"))[finding].status == "confirmed"
    # Роль приложения базы не может обойти веб и подтвердить пункт напрямую.
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.Error):
        conn.execute("select set_config('decimus.remediation_actor', 'employee', true)")
        conn.execute(
            "update inspection_remediation set status='open', revision=revision+1 "
            "where finding_id=%s",
            (finding,),
        )

    # Both evidence and decisions remain reachable beyond the first page.
    with acting_space("GE"):
        reach = reach_of("GE")
        store.transition(
            inspection,
            finding,
            reach=reach,
            actor="partner reviewer",
            action="reopen",
            revision=3,
            reason="Additional evidence",
        )
        for n in range(52):
            evidence.append(
                inspection,
                reach=reach,
                author="employee",
                body=f"Evidence {n}",
                finding_id=finding,
                max_bytes=100,
            )
        first = evidence.list_entries(inspection, finding_id=finding, reach=reach)
        assert len(first.entries) == 50 and first.more
        older = evidence.list_entries(
            inspection, finding_id=finding, reach=reach, before=first.entries[-1].id
        )
        assert len(older.entries) == 3 and not older.more
        assert len({e.id for e in first.entries + older.entries}) == 53
        history = store.events(inspection, finding, reach=reach)
        assert len(history.entries) == 50 and history.more
        previous = store.events(
            inspection, finding, reach=reach, before=history.entries[-1].revision
        )
        assert len(previous.entries) == 6 and not previous.more
        assert sorted(e.revision for e in history.entries + previous.entries) == list(range(1, 57))


def test_preview_storage_failure_removes_original(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db.errors import StorageError
    from src.db.reach import own_reach

    class FailingPreview(Storage):
        def put(self, key: str, data: bytes, *, content_type: str) -> str:
            if key.endswith("/preview.jpg"):
                raise StorageError("preview unavailable")
            return super().put(key, data, content_type=content_type)

    monkeypatch.setattr(evidence, "_check_head", lambda *_a: None)
    monkeypatch.setattr(store, "check_item", lambda *_a, **_k: None)
    image = io.BytesIO()
    Image.new("RGB", (80, 60), "blue").save(image, "PNG")
    disk = FailingPreview()
    with pytest.raises(StorageError):
        evidence.append(
            "11111111-1111-1111-1111-111111111111",
            reach=own_reach("HQ"),
            finding_id="22222222-2222-2222-2222-222222222222",
            author="reviewer",
            body="Evidence",
            file_name="proof.png",
            data=image.getvalue(),
            max_bytes=10000,
            storage=disk,
        )
    assert disk.objects == {}
