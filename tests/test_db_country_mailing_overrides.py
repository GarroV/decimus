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
from src.db import unit_profiles  # noqa: E402

pytestmark = requires_db


@pytest.fixture
def database(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


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
