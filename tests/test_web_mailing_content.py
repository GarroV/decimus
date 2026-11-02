"""Actual template editor/preview/document and plan EML. No outbound communication."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from email import policy
from email.parser import BytesParser
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_action_plans import запрос
from test_web_prescriptions import предписание
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db import (
    action_plans,
    country_mailing_recipients,
    prescriptions,
)
from src.db import (
    mailing_templates as store,
)
from src.db.errors import ConfigError, DbError
from src.domain import mailing_content as mc
from src.web import country_units, mailing_documents

ORIGIN = {"Origin": СВОЙ}


@pytest.fixture
def versions(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[str, str], store.Version]:
    saved: dict[tuple[str, str], store.Version] = {}
    monkeypatch.setattr(
        store,
        "current",
        lambda kind="inspection": {
            ("message", lang): v for (k, lang), v in saved.items() if k == kind
        },
    )
    monkeypatch.setattr(
        store,
        "history",
        lambda slot, lang, kind="inspection": (
            tuple([saved[(kind, lang)]]) if (kind, lang) in saved else ()
        ),
    )

    def save(
        slot: str,
        lang: str,
        body: str | None,
        *,
        actor: str,
        kind: str = "inspection",
        subject: str | None = None,
    ) -> int:
        if body is not None:
            mc.check(kind, subject or "", body)
        old = saved.get((kind, lang))
        saved[(kind, lang)] = store.Version(
            1 if old is None else old.version + 1, body, actor, datetime.now(UTC), subject
        )
        return saved[(kind, lang)].version

    monkeypatch.setattr(store, "save", save)
    return saved


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch, versions: Any) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        yield c


@pytest.mark.parametrize("kind", mc.KINDS)
def test_editor_visible_with_subject_body_fields_and_sample_preview(
    admin: FlaskClient, versions: Any, kind: str
) -> None:
    group = "prescription" if kind == "document" else kind
    page = admin.get(f"/administration?tab=mailings&kind={group}&content={kind}&clang=en")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert 'name="subject"' in html and 'name="body"' in html and 'value="preview"' in html
    subject, body = mc.defaults(kind, "en")
    preview = admin.post(
        f"/administration/mailings/{kind}/content",
        headers=ORIGIN,
        data={"tlang": "en", "subject": subject, "body": body, "action": "preview"},
    )
    assert preview.status_code == 200 and versions == {}
    assert "Example" in preview.get_data(as_text=True)


def test_save_reset_versions_and_failed_input_remains_visible(
    admin: FlaskClient, versions: Any
) -> None:
    path = "/administration/mailings/plan/content"
    bad = admin.post(
        path,
        headers=ORIGIN,
        data={"tlang": "en", "subject": "Plan", "body": "KEEP {bad}", "action": "save"},
    )
    assert bad.status_code == 400 and "KEEP {bad}" in bad.get_data(as_text=True) and versions == {}
    valid = {"tlang": "en", "subject": "Plan {unit}", "body": "Due {due}"}
    assert admin.post(path, headers=ORIGIN, data=valid).status_code == 303
    assert versions[("plan", "en")].subject == valid["subject"]
    assert (
        admin.post(path, headers=ORIGIN, data={"tlang": "en", "action": "reset"}).status_code == 303
    )
    assert versions[("plan", "en")].body is None and versions[("plan", "en")].version == 2


@pytest.mark.parametrize(
    "tenant,role", [("GE", "admin"), ("HQ", "developer"), ("HQ", "osb"), ("HQ", "guest")]
)
def test_unauthorized_editor_and_save_do_not_write(
    monkeypatch: pytest.MonkeyPatch, versions: Any, tenant: str, role: str
) -> None:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        for kind in mc.KINDS:
            assert c.post(
                f"/administration/mailings/{kind}/content", headers=ORIGIN, data={"tlang": "en"}
            ).status_code in (403, 404)
    assert versions == {}


def test_cross_origin_preview_never_writes(admin: FlaskClient, versions: Any) -> None:
    assert (
        admin.post(
            "/administration/mailings/plan/content",
            headers={"Origin": "https://foreign.invalid"},
            data={"action": "preview", "tlang": "en"},
        ).status_code
        == 403
    )
    assert versions == {}


def test_rx_actual_document_uses_template_and_escapes_facts(
    admin: FlaskClient, versions: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = предписание()
    versions[("document", "en")] = store.Version(
        1, "Stored document: {document_body}", "admin", datetime.now(UTC), "Document {title}"
    )
    monkeypatch.setattr(
        prescriptions, "get_prescription", lambda ident, **_: item if ident == item.id else None
    )
    monkeypatch.setattr(country_units, "settings_rows", lambda **_: country_units.UnitsData())
    result = admin.get(f"/actions/prescriptions/{item.id}/document?lang=en")
    html = result.get_data(as_text=True)
    assert result.status_code == 200 and "Stored document:" in html
    assert "<script>alert(1)</script>" not in html
    assert admin.get("/actions/prescriptions/not-found/document").status_code == 404


def test_rx_actual_email_uses_saved_template(versions: Any) -> None:
    item = предписание()
    versions[("prescription", "en")] = store.Version(
        1, "Cover: {document_body}", "admin", datetime.now(UTC), "Mail {title}"
    )
    subject, body = mailing_documents.prescription_message(item, "en")
    assert subject == "Mail " + item.subject and body == "Cover: " + item.body


def test_plan_real_preview_and_eml_use_selected_plan_and_configured_recipients(
    admin: FlaskClient, versions: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = запрос()
    versions[("plan", "en")] = store.Version(
        1, "Selected plan {unit} {due} {plan_url}", "admin", datetime.now(UTC), "Plan {unit}"
    )
    monkeypatch.setattr(
        action_plans, "get_request", lambda ident, **_: item if ident == item.id else None
    )
    monkeypatch.setattr(country_mailing_recipients, "read", lambda _: "country@example.com")
    path = f"/actions/requests/{item.id}/letter?lang=en"
    result = admin.get(path)
    assert result.status_code == 200 and "Selected plan Batumi-1" in result.get_data(as_text=True)
    message = admin.get(path + "&download=eml")
    assert message.status_code == 200 and message.mimetype == "message/rfc822"
    parsed = BytesParser(policy=policy.default).parsebytes(message.data)
    assert str(parsed["To"]) == "country@example.com" and str(parsed["Subject"]) == "Plan Batumi-1"
    assert "id=" + item.id in parsed.get_body(preferencelist=("plain",)).get_content()
    assert admin.get("/actions/requests/not-found/letter").status_code == 404


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("invalid rendered header"),
        DbError("template unavailable"),
        ConfigError("configuration unavailable"),
    ],
)
def test_rx_template_failure_is_handled_before_any_gmail_draft(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    from src.web import auth, guard
    from src.web import prescriptions as web_rx

    outbound: list[Any] = []
    issued: list[bool] = []

    def bad(*args: Any, **kwargs: Any) -> tuple[str, str]:
        raise failure

    def issue(ident: str, *, actor: str, put_draft: Any) -> Any:
        put_draft(предписание())
        issued.append(True)
        return предписание()

    monkeypatch.setattr(web_rx, "is_hq", lambda: True)
    monkeypatch.setattr(guard, "may", lambda _: True)
    monkeypatch.setattr(auth, "current_account", lambda: None)
    monkeypatch.setattr(mailing_documents, "prescription_message", bad)
    monkeypatch.setattr(web_rx.rxw, "issue", issue)
    monkeypatch.setattr(web_rx, "create_draft", lambda *a, **kw: outbound.append(kw))
    app = собрать(tenant="HQ")
    with app.test_request_context("/"):
        response = web_rx._finish_gmail(
            "11111111-1111-1111-1111-111111111111", "en", lambda: "token"
        )
    assert response.status_code == 303 and "gmail=failed" in response.location
    assert outbound == [] and issued == []
