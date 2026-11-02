"""Country contacts: validated inline forms, role boundaries and private references."""

from datetime import UTC, datetime
from html import unescape
from typing import Any

import pytest
import test_web_administration_countries as admin_tests
from flask.testing import FlaskClient
from test_web_country import данные, открыть, с_таблицей, строка_таблицы
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import country_contacts as contacts
from src.db.reach import Reach

главный = admin_tests.главный
записи = admin_tests.записи
осб = admin_tests.осб

URL = "/country/GE/settings/contacts"
IDENT = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def contact_writes(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    writes: list[Any] = []

    def save(country: str, fields: contacts.Fields, **kwargs: Any) -> str:
        fields = contacts.clean(fields)
        writes.append((country, fields, kwargs))
        return IDENT

    monkeypatch.setattr(contacts, "save", save)
    monkeypatch.setattr(contacts, "delete", lambda *args, **kw: writes.append((args, kw)))
    return writes


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_admin_default_inline_country_and_real_name_email(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch, lang: str
) -> None:
    monkeypatch.setattr(
        contacts,
        "for_country",
        lambda country: (
            contacts.Contact(
                IDENT, country, "partner", "Actual Partner", "owner@example.com", datetime.now(UTC)
            ),
        ),
    )
    page = главный.get(f"/administration?tab=countries&lang={lang}").get_data(as_text=True)
    assert "countryadmininline__detail" in page
    assert "sdrawer__panel" not in page and "data-drawer-open" not in page
    assert "Actual Partner" in page and "owner@example.com" in page
    assert "/country/AM/settings/contacts" in page
    assert 'name="space"' not in page


def test_save_form_uses_post_and_no_private_query(
    главный: FlaskClient, contact_writes: list[Any]
) -> None:
    response = главный.post(
        URL,
        data={"kind": "mailing", "name": "Audits", "email": "audit@example.com"},
        headers={"Origin": СВОЙ},
    )
    assert response.status_code == 303
    assert "audit@example.com" not in response.location
    assert contact_writes[0][0:2] == (
        "GE",
        contacts.Fields("mailing", "Audits", "audit@example.com"),
    )
    assert contact_writes[0][2]["actor"]


def test_invalid_fields_stay_in_html_without_redirect_or_cookie(
    главный: FlaskClient, contact_writes: list[Any]
) -> None:
    response = главный.post(
        URL,
        data={"kind": "mailing", "name": "Attempted Name", "email": "not-an-address"},
        headers={"Origin": СВОЙ},
    )
    assert response.status_code == 400
    page = unescape(response.get_data(as_text=True))
    assert 'value="Attempted Name"' in page and 'value="not-an-address"' in page
    assert contact_writes == []
    assert "Attempted Name" not in str(response.headers)


def test_foreign_origin_country_and_role_never_write(
    главный: FlaskClient, contact_writes: list[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    fields = {"kind": "partner", "name": "Owner"}
    assert (
        главный.post(URL, data=fields, headers={"Origin": "https://foreign.example"}).status_code
        == 403
    )
    monkeypatch.setattr("src.web.auth.reach_of", lambda tenant: Reach(tenant, None, ("AM",)))
    monkeypatch.setattr("src.web.country.countries", lambda **kw: (("AM", 1),))
    assert главный.post(URL, data=fields, headers={"Origin": СВОЙ}).status_code == 404
    assert contact_writes == []


def test_osb_contact_write_forbidden(осб: FlaskClient, contact_writes: list[Any]) -> None:
    assert (
        осб.post(
            URL, data={"kind": "partner", "name": "Owner"}, headers={"Origin": СВОЙ}
        ).status_code
        == 403
    )
    assert contact_writes == []


def test_partner_reference_never_queries_private_contacts(
    monkeypatch: pytest.MonkeyPatch, записи: dict[str, Any]
) -> None:
    подменить_двери(monkeypatch, tenant="LOTOS", role="admin")
    monkeypatch.setattr("src.web.auth.reach_of", lambda tenant: Reach(tenant, None, ("GE",)))

    def private(*args: Any) -> Any:
        raise AssertionError("partner must not read private contact data")

    monkeypatch.setattr(contacts, "for_country", private)
    с_таблицей(monkeypatch, строка_таблицы(partner="Imported Legal Name"))
    with собрать(tenant="LOTOS").test_client() as client:
        assert войти(client).status_code == 302
        page = открыть(client, monkeypatch, данные(), "/country/GE?reference=partner")
        assert "Imported Legal Name" in page
        assert "reference=mailing" not in page
        assert client.get("/country/GE?reference=mailing").status_code == 404
        assert 'name="email"' not in page


def test_hq_mailing_reference_is_read_only(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        contacts,
        "for_country",
        lambda code: (
            contacts.Contact(
                IDENT,
                code,
                "mailing",
                "Inspection Contact",
                "private@example.com",
                datetime.now(UTC),
            ),
        ),
    )
    page = открыть(главный, monkeypatch, данные(), "/country/GE?reference=mailing")
    assert "private@example.com" in page and "Inspection Contact" in page
    assert 'name="email"' not in page
    assert "/settings/contacts" not in page


def test_unavailable_contact_storage_preserves_form(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.db.errors import DbError

    def unavailable(*args: Any, **kwargs: Any) -> str:
        raise DbError("configuration unavailable")

    monkeypatch.setattr(contacts, "save", unavailable)
    response = главный.post(
        URL,
        data={"kind": "mailing", "name": "Retained Name", "email": "retained@example.com"},
        headers={"Origin": СВОЙ},
    )
    assert response.status_code == 503
    page = response.get_data(as_text=True)
    assert 'value="Retained Name"' in page and 'value="retained@example.com"' in page
