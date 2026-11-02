"""Country contacts: explicit/empty defaults, scoped contact-only edits and permissions."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import country_contacts, country_contracts, country_mailing_recipients, unit_profiles
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
    out: dict[str, list[Any]] = {"units": [], "recipients": []}
    monkeypatch.setattr(
        country_units, "settings_rows", lambda **_: country_units.UnitsData(rows=(ROW,))
    )
    monkeypatch.setattr(
        unit_profiles, "update_contacts", lambda *a, **kw: out["units"].append((a, kw))
    )
    monkeypatch.setattr(
        country_mailing_recipients, "save", lambda *a, **kw: out["recipients"].append((a, kw))
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


def test_empty_override_and_reset_are_distinct(admin: FlaskClient, calls: Any) -> None:
    for data in ({"recipients": ""}, {"reset": "1"}):
        response = admin.post("/country/RS/settings/recipients", headers=ORIGIN, data=data)
        assert response.status_code == 302 and "saved=ok" in response.location
    assert [x[1]["reset"] for x in calls["recipients"]] == [False, True]
    assert all(x[1]["actor"] for x in calls["recipients"])


@pytest.mark.parametrize("tenant,role", [("RS", "admin"), ("HQ", "guest"), ("HQ", "osb")])
def test_unauthorized_mutations_never_write(
    monkeypatch: pytest.MonkeyPatch, calls: Any, tenant: str, role: str
) -> None:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        for path in ("/country/RS/unit-profile", "/country/RS/settings/recipients"):
            assert c.post(path, headers=ORIGIN, data={"unit_key": ROW.key}).status_code in (
                403,
                404,
            )
    assert calls == {"units": [], "recipients": []}


def test_foreign_origin_never_writes(admin: FlaskClient, calls: Any) -> None:
    for path in ("/country/RS/unit-profile", "/country/RS/settings/recipients"):
        assert (
            admin.post(
                path, headers={"Origin": "https://foreign.invalid"}, data={"unit_key": ROW.key}
            ).status_code
            == 403
        )
    assert calls == {"units": [], "recipients": []}


@pytest.mark.parametrize("configured", ["", "country@example.com"])
def test_explicit_country_defaults_even_empty_do_not_fall_back(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: configured)
    monkeypatch.setattr(
        country_contracts,
        "dkk_recipients",
        lambda _: pytest.fail("must not read contract fallback"),
    )
    assert prescriptions._default_recipients("RS") == configured


def test_absent_country_override_keeps_legacy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: None)
    monkeypatch.setattr(country_contacts, "for_country", lambda _: ())
    monkeypatch.setattr(country_contracts, "dkk_recipients", lambda _: "contract@example.com")
    assert prescriptions._default_recipients("RS") == "contract@example.com"


def test_unread_configuration_does_not_expose_old_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_: str) -> str:
        raise DbError("not available")

    monkeypatch.setattr(country_mailing_recipients, "read", fail)
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


def test_administration_exposes_primary_contacts_and_keeps_contract_additional(
    admin: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.web import country as country_data

    monkeypatch.setattr(country_data, "countries", lambda **_: (("RS", 1),))
    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: "country@example.com")
    response = admin.get("/administration?tab=countries&country=RS&lang=en")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="developer"' in html
    assert 'name="recipients"' in html and "country@example.com" in html
    assert 'name="unit_key" value="unit-1"' in html
    assert 'name="address"' in html and 'name="partner_email"' in html
    assert html.index('id="cb-recipients"') < html.index('id="cb-contract"')
    assert "Additional: contract</summary>" in html


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


def test_reader_sees_explicit_empty_as_empty_not_legacy(
    admin: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.web import country as country_data
    from src.web import guard

    original = guard.may
    monkeypatch.setattr(
        guard, "may", lambda action: False if action == "mailing.manage" else original(action)
    )
    monkeypatch.setattr(country_data, "countries", lambda **_: (("RS", 1),))
    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: "")
    html = admin.get("/administration?tab=countries&country=RS&lang=en").get_data(as_text=True)
    assert "The configured list is empty" in html
    assert "Using the configured list, including when empty." in html
    assert "Using legacy defaults:" not in html


def test_default_rx_plan_recipients_inherit_main_directory_without_duplicate_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: None)
    monkeypatch.setattr(
        country_contacts,
        "for_country",
        lambda _: (
            SimpleNamespace(kind="mailing", email="shared@example.com"),
            SimpleNamespace(kind="partner", email="partner@example.com"),
        ),
    )
    assert country_mailing_recipients.effective("RS") == "shared@example.com"
    assert prescriptions._default_recipients("RS") == "shared@example.com"
    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: "")
    assert country_mailing_recipients.effective("RS") == ""


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
