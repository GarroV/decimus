"""Country recipient PII and non-destructive profile edits against PostgreSQL."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

psycopg = pytest.importorskip("psycopg")
from src.db import country_mailing_recipients as recipients  # noqa: E402
from src.db import unit_profiles  # noqa: E402
from src.db.errors import PrescriptionError  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def database(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def test_explicit_empty_reset_and_remembered_addresses_independent(
    database: str, pg_dsn: str
) -> None:
    assert recipients.read("RS") is None
    recipients.save("RS", "A@EXAMPLE.COM; b@example.com", actor="admin")
    assert recipients.read("RS") == "a@example.com, b@example.com"
    assert recipients.read("GE") is None
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "insert into country_recipients(country,recipients,updated_by) "
            "values ('RS','legacy@example.com','admin')"
        )
    assert recipients.read("RS") == "a@example.com, b@example.com"
    recipients.save("RS", "", actor="admin")
    assert recipients.read("RS") == ""
    recipients.save("RS", "bad unsaved input", actor="admin", reset=True)
    assert recipients.read("RS") is None


def test_invalid_recipients_keep_previous_value(database: str) -> None:
    recipients.save("RS", "a@example.com", actor="admin")
    with pytest.raises(PrescriptionError):
        recipients.save("RS", "a@example.com\r\nBcc: bad@example.com", actor="admin")
    assert recipients.read("RS") == "a@example.com"


def test_contact_edit_preserves_entire_imported_profile_and_clears_fields(database: str) -> None:
    original = unit_profiles.Profile(
        country_code="RS",
        name="Belgrade-1",
        name_normalized="belgrade1",
        dodo_id="a" * 32,
        stage="closed",
        status="closed by partner",
        city="Belgrade",
        address="old",
        partner="old partner",
        partner_email="old@example.com",
        restaurant_on=date(2020, 1, 1),
        delivery_on=date(2020, 2, 1),
        revenue_on=date(2020, 3, 1),
        closed_on=date(2026, 1, 1),
        total_area=Decimal("123"),
        seats=17,
        extra={"preserve": "source"},
    )
    unit_profiles.save(
        (
            original,
            replace(
                original,
                country_code="GE",
                name="Batumi-1",
                name_normalized="batumi1",
                dodo_id="b" * 32,
            ),
        )
    )
    unit_profiles.update_contacts(
        "RS",
        "belgrade1",
        name="ignored name",
        dodo_id="a" * 32,
        address="new",
        partner="new partner",
        partner_email="new@example.com",
    )
    assert unit_profiles.by_country("RS")[0] == replace(
        original, address="new", partner="new partner", partner_email="new@example.com"
    )
    assert unit_profiles.by_country("GE")[0].address == "old"
    unit_profiles.update_contacts(
        "RS",
        "belgrade1",
        name="ignored",
        dodo_id="a" * 32,
        address="",
        partner="",
        partner_email="",
    )
    assert unit_profiles.by_country("RS")[0] == replace(
        original, address="", partner="", partner_email=""
    )


def test_application_cannot_write_country_recipients(database: str, db_env: str) -> None:
    with psycopg.connect(db_env) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "insert into country_mailing_recipients(country,recipients,updated_by) "
            "values('RS','a@example.com','bot')"
        )


def test_country_recipient_pii_is_hq_only(database: str, db_env: str) -> None:
    recipients.save("RS", "a@example.com", actor="admin")
    for space, expected in (("HQ", 1), ("*", 1), ("RS", 0)):
        with psycopg.connect(db_env) as conn:
            conn.execute("select set_config('decimus.space', %s, false)", (space,))
            row = conn.execute("select count(*) from country_mailing_recipients").fetchone()
            assert row is not None and row[0] == expected


@pytest.mark.parametrize(
    "value",
    [
        "bad",
        "a@example.com\r\nBcc: bad@example.com",
        "a@example.com,b@example.com",
        "A@EXAMPLE.COM",
    ],
)
def test_database_itself_refuses_invalid_country_headers(database: str, value: str) -> None:
    with psycopg.connect(database) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into country_mailing_recipients (country, recipients, updated_by) "
            "values ('RS', %s, 'admin')",
            (value,),
        )
