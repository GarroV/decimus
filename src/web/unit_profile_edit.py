"""Edit existing pizzeria contact fields from the country card. HQ, scoped, no identity edits."""

from __future__ import annotations

from collections.abc import Mapping

from flask import Flask, abort, redirect, request
from werkzeug.wrappers import Response

from src.db import unit_profiles
from src.db.errors import DbError, MailingCcError
from src.db.mailing_cc import clean_email
from src.ratings.svod import normalize

from . import administration, auth, country_units, guard, unit_add
from .config import Settings
from .origin import refuse_foreign_origin
from .users_view import TAB_COUNTRIES


def contacts(form: Mapping[str, str]) -> tuple[str, str, str]:
    values = form
    out = []
    for key, limit in (("address", 200), ("partner", 120)):
        value = str(values.get(key) or "").strip()
        if len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid contact field")
        out.append(value)
    raw = str(values.get("partner_email") or "").strip()
    return out[0], out[1], clean_email(raw) if raw else ""


def install(app: Flask, conf: Settings) -> None:
    @app.post("/country/<code>/unit-profile", endpoint="unit_profile_save")
    @guard.action("space.manage")
    def save(code: str) -> Response:
        country = unit_add._gate(code)
        refuse_foreign_origin()
        key = request.form.get("unit_key", "")
        try:
            rows = country_units.settings_rows(reach=auth.current_reach(), code=country)
        except DbError:
            return redirect(administration.url(TAB_COUNTRIES, country=country, saved="failed"))
        row = rows.find(key)
        if row is None:
            abort(404)
        try:
            address, partner, email = contacts(request.form)
            unit_profiles.update_contacts(
                country,
                row.profile_key or normalize(row.name),
                name=row.name,
                dodo_id=row.code or None,
                address=address,
                partner=partner,
                partner_email=email,
            )
        except (ValueError, MailingCcError):
            return redirect(
                administration.url(TAB_COUNTRIES, country=country, saved="contacts_invalid")
            )
        except DbError:
            return redirect(administration.url(TAB_COUNTRIES, country=country, saved="failed"))
        return redirect(administration.url(TAB_COUNTRIES, country=country, saved="ok"))
