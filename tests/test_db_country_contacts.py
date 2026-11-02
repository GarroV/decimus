"""Contacts persist independently of access spaces and never leak to partners."""

from datetime import date

import psycopg
import pytest
from conftest import requires_db
from db_harness import set_retraction_env

from src.db import country_contacts as contacts
from src.db.reach import Reach
from src.db.space import acting_space

pytestmark = requires_db


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def test_contacts_persist_and_are_hq_only(db_env: str, admin_env: str) -> None:
    with acting_space("HQ"):
        ident = contacts.save(
            "GE", contacts.Fields("partner", "Owner", "owner@example.com"), actor="admin"
        )
        contacts.save(
            "GE", contacts.Fields("mailing", "Audits", "audit@example.com"), actor="admin"
        )
        contacts.save("GE", contacts.Fields("partner", "Second owner"), actor="admin")
        assert contacts.partner_names() == {"GE": ("Owner", "Second owner")}
        rows = contacts.for_country("GE")
        assert len(rows) == 3
        contacts.save(
            "GE",
            contacts.Fields("partner", "Updated", "owner@example.com"),
            actor="admin",
            ident=ident,
        )
        assert next(r for r in contacts.for_country("GE") if r.id == ident).name == "Updated"
        with pytest.raises(contacts.ContactError, match="missing"):
            contacts.delete("RS", ident, actor="admin")
        with pytest.raises(contacts.ContactError, match="missing"):
            contacts.save(
                "RS", contacts.Fields("partner", "Wrong country"), actor="admin", ident=ident
            )
        with pytest.raises(contacts.ContactError, match="duplicate"):
            contacts.save(
                "GE", contacts.Fields("partner", "Duplicate", "OWNER@example.com"), actor="admin"
            )
    with acting_space("GE"):
        assert contacts.for_country("GE") == ()
        assert contacts.partner_names() == {}
        with pytest.raises(contacts.ContactError, match="forbidden"):
            contacts.save("GE", contacts.Fields("partner", "Unexpected"), actor="partner")
    with acting_space("HQ"):
        contacts.delete("GE", ident, actor="admin")
        assert len(contacts.for_country("GE")) == 2


def test_app_cannot_write_and_database_checks_email(db_env: str, admin_env: str) -> None:
    sql = (
        "insert into country_contacts(country,kind,name,email,updated_by) "
        "values ('GE','mailing','Audit',%s,'admin')"
    )
    with psycopg.connect(db_env) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(sql, ("audit@example.com",))
    for invalid in ("bad", "a@example.com, b@example.com", "a@example.com\r\nBcc:x@example.com"):
        with psycopg.connect(admin_env) as conn:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(sql, (invalid,))


def test_inspection_recipients_follow_unit_id_and_required_reach(
    pg_dsn: str, db_env: str, admin_env: str
) -> None:
    ids = []
    with psycopg.connect(pg_dsn) as conn:
        for code, name in (("GE", "Unit One"), ("RS", "Unit Two")):
            unit = conn.execute(
                "insert into units(tenant_code,name,name_normalized,country) "
                "values ('HQ',%s,%s,%s) returning id",
                (name, name.lower(), code),
            ).fetchone()[0]
            ident = conn.execute(
                "insert into inspections(tenant_code,unit_id,chat_id,kind,"
                "inspection_date,report_lang,"
                "ui_lang,speech_lang,checklist_version,pct,grade,source_fingerprint,"
                "status,origin,reported_pct) "
                "values ('HQ',%s,0,'planned',%s,'ru','ru','ru','v1',95,'B',%s,"
                "'finalized','legacy',95) returning id",
                (unit, date(2026, 1, 1), code),
            ).fetchone()[0]
            ids.append(str(ident))
    with acting_space("HQ"):
        contacts.save("GE", contacts.Fields("partner", "Owner", "owner@example.com"), actor="admin")
        contacts.save(
            "GE", contacts.Fields("mailing", "Audits", "audit@example.com"), actor="admin"
        )
        contacts.save(
            "RS", contacts.Fields("mailing", "Audits", "serbia@example.com"), actor="admin"
        )
        hq = Reach("HQ", None, None)
        assert contacts.recipients_for_inspection(ids[0], reach=hq) == "audit@example.com"
        assert contacts.recipients_for_inspection(ids[1], reach=hq) == "serbia@example.com"
        assert contacts.recipients_for_inspection(ids[0], reach=Reach("HQ", None, ("RS",))) == ""
    with acting_space("GE"):
        assert contacts.recipients_for_inspection(ids[0], reach=Reach("GE", None, ("GE",))) == ""


def test_admin_cannot_change_contact_country_kind_or_id(db_env: str, admin_env: str) -> None:
    with acting_space("HQ"):
        ident = contacts.save("GE", contacts.Fields("partner", "Owner"), actor="admin")
    for field, value in (
        ("country", "RS"),
        ("kind", "mailing"),
        ("id", "11111111-1111-1111-1111-111111111111"),
    ):
        with psycopg.connect(admin_env) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    psycopg.sql.SQL("update country_contacts set {}=%s where id=%s").format(
                        psycopg.sql.Identifier(field)
                    ),
                    (value, ident),
                )


def test_real_web_save_reference_recipient_update_delete(
    pg_dsn: str, db_env: str, admin_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from web_harness import СВОЙ, войти, подменить_двери, собрать

    from src.web import inspections, letter_draft

    with psycopg.connect(pg_dsn) as conn:
        unit = conn.execute(
            "insert into units(tenant_code,name,name_normalized,country,city) "
            "values ('HQ','Contact Flow Unit','contact flow unit','GE','Tbilisi') returning id"
        ).fetchone()[0]
        inspection = str(
            conn.execute(
                "insert into inspections(tenant_code,unit_id,chat_id,kind,inspection_date,"
                "report_lang,ui_lang,speech_lang,checklist_version,pct,grade,source_fingerprint,"
                "status,origin,reported_pct) values ('HQ',%s,0,'planned',%s,'ru','ru','ru','v1',"
                "95,'B','contact-flow','finalized','legacy',95) returning id",
                (unit, date(2026, 1, 1)),
            ).fetchone()[0]
        )
    traces = подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        base = "/country/GE/settings/contacts"
        response = client.post(
            base,
            data={"kind": "mailing", "name": "Flow Contact", "email": "flow@example.com"},
            headers={"Origin": СВОЙ},
        )
        assert response.status_code == 303
        admin = client.get(response.location)
        assert admin.status_code == 200 and "flow@example.com" in admin.get_data(as_text=True)
        reference = client.get("/country/GE?reference=mailing")
        assert reference.status_code == 200
        assert "flow@example.com" in reference.get_data(as_text=True)
        assert 'name="email"' not in reference.get_data(as_text=True)
        with acting_space("HQ"):
            (row,) = contacts.for_country("GE")
            detail = inspections.load_card(inspection, reach=Reach("HQ", None, None))
            assert detail is not None
            assert (
                letter_draft._inspection_to(detail, reach=Reach("HQ", None, None))
                == "flow@example.com"
            )
        response = client.post(
            base,
            data={
                "id": row.id,
                "kind": "mailing",
                "name": "Updated Contact",
                "email": "updated@example.com",
            },
            headers={"Origin": СВОЙ},
        )
        assert response.status_code == 303
        assert "updated@example.com" in client.get("/country/GE?reference=mailing").get_data(
            as_text=True
        )
        response = client.post(base + "/" + row.id + "/delete", headers={"Origin": СВОЙ})
        assert response.status_code == 303
        with acting_space("HQ"):
            assert contacts.for_country("GE") == ()
            assert letter_draft._inspection_to(detail, reach=Reach("HQ", None, None)) == ""
    assert all(
        "flow@example.com" not in trace["target"] and "updated@example.com" not in trace["target"]
        for trace in traces["action_journal"]
    )
