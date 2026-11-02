"""Validated country-contact writes; HQ administration only, without outbound mail."""

from __future__ import annotations

from flask import Flask, abort, g, make_response, redirect, request
from werkzeug.wrappers import Response

from src.db import country_contacts as contacts
from src.db.errors import DbError
from src.domain.errors import ConfigError

from . import administration, auth, countries_screen, guard
from . import country as country_data
from .origin import refuse_foreign_origin


def install(app: Flask, conf_lang: str) -> None:
    """Install country-bound, same-origin administration contact forms."""

    def checked(raw: str) -> str:
        g.journal_target = "country_contacts"
        refuse_foreign_origin()
        code = country_data.normalize_code(raw)
        visible = {c for c, _ in country_data.countries(reach=auth.current_reach())}
        if code not in visible:
            abort(404)
        return code

    def failed(code: str, fields: contacts.Fields, ident: str, error: str) -> Response:
        page, _status = countries_screen.show(
            conf_lang,
            selected=code,
            contact_error=error,
            contact_draft=contacts.Fields(
                fields.kind if fields.kind in contacts.KINDS else contacts.PARTNER,
                fields.name,
                fields.email,
            ),
            contact_ident=ident,
        )
        return make_response(page, 503 if error == "unavailable" else 400)

    @app.post("/country/<code>/settings/contacts", endpoint="country_contact_save")
    @guard.action("space.manage")
    def save(code: str) -> Response:
        code = checked(code)
        account = auth.current_account()
        if account is None:
            abort(403)
        fields = contacts.Fields(*(request.form.get(key, "") for key in ("kind", "name", "email")))
        ident = request.form.get("id", "")
        try:
            contacts.save(code, fields, actor=account.login, ident=ident)
        except contacts.ContactError as exc:
            return failed(code, fields, ident, exc.code)
        except (DbError, ConfigError):
            return failed(code, fields, ident, "unavailable")
        return redirect(administration.url("countries", country=code, saved="ok"), code=303)

    @app.post("/country/<code>/settings/contacts/<ident>/delete", endpoint="country_contact_delete")
    @guard.action("space.manage")
    def delete(code: str, ident: str) -> Response:
        code = checked(code)
        account = auth.current_account()
        if account is None:
            abort(403)
        try:
            contacts.delete(code, ident, actor=account.login)
        except contacts.ContactError as exc:
            return failed(code, contacts.Fields("partner"), ident, exc.code)
        except (DbError, ConfigError):
            return failed(code, contacts.Fields("partner"), ident, "unavailable")
        return redirect(administration.url("countries", country=code, saved="ok"), code=303)
