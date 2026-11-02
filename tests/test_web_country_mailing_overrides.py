"""Country contacts: explicit/empty defaults, scoped contact-only edits and permissions."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import country_contacts, unit_profiles
from src.db.errors import DbError
from src.db.reach import Reach
from src.web import auth, country_units, prescriptions, unit_profile_edit

ORIGIN = {"Origin": СВОЙ}
ROW = country_units.UnitRow(
    key="unit-1",
    name="Belgrade-1",
    unit_id="unit-1",
    stage="closed",
    code="a" * 32,
    profile_key="belgrade1",
)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    monkeypatch.setattr(country_contacts, "for_country", lambda _: ())
    out: dict[str, list[Any]] = {"units": []}
    monkeypatch.setattr(
        country_units, "settings_rows", lambda **_: country_units.UnitsData(rows=(ROW,))
    )
    monkeypatch.setattr(
        unit_profiles, "update_contacts", lambda *a, **kw: out["units"].append((a, kw))
    )
    return out


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch, calls: Any) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        yield c


def test_unit_edit_only_changes_contacts_not_submitted_identity(
    admin: FlaskClient, calls: Any
) -> None:
    response = admin.post(
        "/country/RS/unit-profile",
        headers=ORIGIN,
        data={
            "unit_key": ROW.key,
            "address": " New address ",
            "partner": "New partner",
            "partner_email": "A@EXAMPLE.COM",
            "name": "ATTACK",
            "dodo_id": "b" * 32,
            "stage": "open",
            "country": "GE",
        },
    )
    assert response.status_code == 302 and "saved=ok" in response.location
    args, fields = calls["units"][0]
    assert args == ("RS", "belgrade1")
    assert fields == {
        "name": ROW.name,
        "dodo_id": ROW.code,
        "address": "New address",
        "partner": "New partner",
        "partner_email": "a@example.com",
    }


@pytest.mark.parametrize(
    "data",
    [
        {"address": "x" * 201},
        {"address": "a\nb"},
        {"partner_email": "x@example.com\r\nBcc: bad@example.com"},
        {"partner_email": "bad"},
    ],
)
def test_invalid_contact_never_reaches_write(
    admin: FlaskClient, calls: Any, data: dict[str, str]
) -> None:
    response = admin.post(
        "/country/RS/unit-profile", headers=ORIGIN, data={"unit_key": ROW.key, **data}
    )
    assert response.status_code == 302 and "contacts_invalid" in response.location
    assert calls["units"] == []


def test_unknown_or_out_of_reach_unit_never_writes(
    admin: FlaskClient, calls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (
        admin.post(
            "/country/RS/unit-profile", headers=ORIGIN, data={"unit_key": "other"}
        ).status_code
        == 404
    )
    monkeypatch.setattr(
        auth, "current_reach", lambda: Reach(tenant="HQ", tenants=None, countries=("RS",))
    )
    assert (
        admin.post(
            "/country/GE/unit-profile", headers=ORIGIN, data={"unit_key": ROW.key}
        ).status_code
        == 404
    )
    assert calls["units"] == []


@pytest.mark.parametrize("tenant,role", [("RS", "admin"), ("HQ", "guest"), ("HQ", "osb")])
def test_unauthorized_mutations_never_write(
    monkeypatch: pytest.MonkeyPatch, calls: Any, tenant: str, role: str
) -> None:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        assert c.post(
            "/country/RS/unit-profile", headers=ORIGIN, data={"unit_key": ROW.key}
        ).status_code in (403, 404)
    assert calls == {"units": []}


def test_foreign_origin_never_writes(admin: FlaskClient, calls: Any) -> None:
    assert (
        admin.post(
            "/country/RS/unit-profile",
            headers={"Origin": "https://foreign.invalid"},
            data={"unit_key": ROW.key},
        ).status_code
        == 403
    )
    assert calls == {"units": []}


def test_mailing_list_fills_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        country_contacts,
        "for_country",
        lambda _: (
            SimpleNamespace(kind="mailing", email="shared@example.com"),
            SimpleNamespace(kind="mailing", email="shared@example.com"),
            SimpleNamespace(kind="mailing", email="second@example.com"),
            SimpleNamespace(kind="partner", email="partner@example.com"),
        ),
    )
    assert country_contacts.mailing_to("RS") == "shared@example.com, second@example.com"
    assert prescriptions._default_recipients("RS") == "shared@example.com, second@example.com"


def test_empty_mailing_list_falls_back_to_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        country_contacts,
        "for_country",
        lambda _: (SimpleNamespace(kind="partner", email="p@x.io"),),
    )
    monkeypatch.setattr(prescriptions.rx, "remembered_recipients", lambda _: "old@example.com")
    assert country_contacts.mailing_to("RS") is None
    assert prescriptions._default_recipients("RS") == "old@example.com"


def test_unread_mailing_list_does_not_expose_old_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_: str) -> tuple[()]:
        raise DbError("not available")

    monkeypatch.setattr(country_contacts, "for_country", fail)
    assert prescriptions._default_recipients("RS") == ""


def test_contact_validator_accepts_clearing() -> None:
    assert unit_profile_edit.contacts({}) == ("", "", "")


def test_new_pizzeria_email_is_validated_and_carried_into_profile() -> None:
    from src.web import unit_add

    extras = unit_add.parse_extras({"partner_email": "A@EXAMPLE.COM"})
    assert not extras.is_empty
    assert (
        unit_add.merged_profile("RS", "Belgrade-2", extras, None).partner_email == "a@example.com"
    )
    with pytest.raises(unit_add.ExtrasRefused):
        unit_add.parse_extras({"partner_email": "a@example.com\r\nBcc: bad@example.com"})


def test_administration_exposes_primary_contacts(
    admin: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.web import country as country_data

    monkeypatch.setattr(country_data, "countries", lambda **_: (("RS", 1),))
    response = admin.get("/administration?tab=countries&country=RS&lang=en")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="developer"' in html
    assert 'name="recipients"' not in html and "settings/recipients" not in html
    assert html.count("Mailing recipients") == 1
    assert 'name="unit_key" value="unit-1"' in html
    assert 'name="address"' in html and 'name="partner_email"' in html
    assert "contract" not in html.lower().replace("contacts", ""), "договора страны нет (D702)"


def test_profile_read_failure_never_becomes_empty_overwrite(
    admin: FlaskClient, calls: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**kwargs: Any) -> country_units.UnitsData:
        raise DbError("not available")

    monkeypatch.setattr(country_units, "settings_rows", fail)
    response = admin.post(
        "/country/RS/unit-profile", headers=ORIGIN, data={"unit_key": ROW.key, "address": "new"}
    )
    assert response.status_code == 302 and "saved=failed" in response.location
    assert calls["units"] == []


def test_developer_cannot_edit_administrative_pizzeria_contacts(
    monkeypatch: pytest.MonkeyPatch, calls: Any
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="developer")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        assert client.post(
            "/country/RS/unit-profile", headers=ORIGIN, data={"unit_key": ROW.key}
        ).status_code in (403, 404)
    assert calls["units"] == []
