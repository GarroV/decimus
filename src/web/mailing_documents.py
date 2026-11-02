"""Actual plan letter and prescription document consumers; no sending."""

from __future__ import annotations

from flask import Flask, abort, render_template, request, url_for
from flask import Response as FlaskResponse

from src.db import action_plans, country_mailing_recipients, mailing_templates, prescriptions
from src.db.models import InspectionDetail
from src.domain import mailing_content
from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.report.letter_markup import from_plain, to_plain

from . import auth, country_units, guard, mailings_content, ui_lang
from .geo_names import country_title
from .google_mail import letter_message
from .mailing_copy import cc_for


def rx_facts(
    item: prescriptions.Prescription, lang: str, *, addresses: bool = False
) -> dict[str, str]:
    address_lines: list[str] = []
    if addresses:
        rows = country_units.settings_rows(reach=auth.current_reach(), code=item.country).rows
        selected = {unit.id for unit in item.units}
        address_lines = [
            f"{row.name}: {row.address or '—'}"
            for row in rows
            if not selected or row.unit_id in selected
        ]
    return {
        "title": item.subject,
        "document_body": item.body,
        "country": country_title(item.country, lang) or item.country,
        "date": str((item.issued_at or item.created_at).date()),
        "due": str(item.due_on),
        "units": "\n".join(unit.name for unit in item.units)
        or ("Вся страна" if lang == "ru" else "Whole country"),
        "addresses": "\n".join(address_lines) or "—",
        "bases": "\n".join(
            f"{base.unit_name} · {base.inspection_date}" for base in item.bases if base.known
        )
        or "—",
    }


def prescription_message(item: prescriptions.Prescription, lang: str) -> tuple[str, str]:
    return mailings_content.render("prescription", lang, rx_facts(item, lang))


def inspection_message(
    detail: InspectionDetail, lang: str, subject: str, html_body: str
) -> tuple[str, str]:
    if canonical_tenant(detail.inspection.tenant_code) != HQ_TENANT:
        return subject, html_body
    version = mailing_templates.current("inspection").get(("message", lang))
    if version is None or version.body is None:
        return subject, html_body
    values = {
        "unit": detail.inspection.unit_name,
        "city": detail.inspection.city,
        "date": str(detail.inspection.inspection_date),
        "letter_body": to_plain(html_body),
    }
    header, body = mailing_content.render(
        "inspection", version.subject or subject, version.body, values
    )
    return header, html_body if version.body == "{letter_body}" else from_plain(body)


def install(app: Flask, conf_lang: str) -> None:
    @app.get("/actions/prescriptions/<ident>/document", endpoint="prescription_document")
    @guard.action("view.actions")
    def document(ident: str) -> str:
        lang = ui_lang.request_lang(conf_lang)
        item = prescriptions.get_prescription(ident, reach=auth.current_reach())
        if item is None:
            abort(404)
        # Template configuration is HQ-only. Partners get the neutral built-in document.
        facts = rx_facts(item, lang, addresses=True)
        if auth.current_tenant() == "HQ":
            heading, body = mailings_content.render("document", lang, facts)
        else:
            heading, body = mailing_content.render(
                "document", *mailing_content.defaults("document", lang), facts
            )
        return render_template(
            "mailings/document.html", heading=heading, body=from_plain(body), lang=lang
        )

    @app.get("/actions/requests/<ident>/letter", endpoint="plan_letter_preview")
    @guard.action("plan.manage")
    def plan_letter(ident: str) -> str | FlaskResponse:
        lang = ui_lang.request_lang(conf_lang)
        plan = action_plans.get_request(ident, reach=auth.current_reach())
        if plan is None:
            abort(404)
        values = {
            "country": country_title(plan.country, lang) or plan.country or "",
            "unit": plan.unit_name,
            "date": str(plan.inspection_date),
            "due": str(plan.due_on),
            "plan_url": url_for("actions", tab="plans", id=plan.id, _external=True),
        }
        subject, body = mailings_content.render("plan", lang, values)
        to = country_mailing_recipients.read(plan.country) if plan.country else None
        if request.args.get("download") == "eml":
            message = letter_message(
                to=to or "", cc=cc_for("plan"), subject=subject, body=from_plain(body)
            )
            return FlaskResponse(
                message.as_bytes(),
                mimetype="message/rfc822",
                headers={"Content-Disposition": 'attachment; filename="action-plan.eml"'},
            )
        return render_template(
            "mailings/plan_letter.html",
            subject=subject,
            body=from_plain(body),
            to=to or "",
            lang=lang,
            download=url_for("plan_letter_preview", ident=ident, lang=lang, download="eml"),
        )
