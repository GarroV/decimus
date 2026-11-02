"""Message template editor/preview; no outbound communication."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import Flask, abort, redirect, render_template, request
from werkzeug.wrappers import Response

from src.db import mailing_templates as store
from src.db.errors import DbError, MailingTemplateInputError
from src.domain import mailing_content as content

from . import administration, auth, guard, ui_lang
from .origin import refuse_foreign_origin
from .users_view import TAB_MAILINGS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContentEditor:
    kind: str
    lang: str
    subject: str
    body: str
    version: store.Version | None
    history: tuple[store.Version, ...]
    fields: tuple[str, ...]
    preview_subject: str = ""
    preview_body: str = ""
    error: str = ""


def current(kind: str, lang: str) -> tuple[str, str]:
    builtin = content.defaults(kind, lang)
    now = store.current(kind).get(("message", lang))
    return (now.subject or builtin[0], now.body) if now and now.body is not None else builtin


def render(kind: str, lang: str, values: dict[str, str]) -> tuple[str, str]:
    subject, body = current(kind, lang)
    return content.render(kind, subject, body, values)


def editor(
    kind: str,
    lang: str,
    *,
    typed: tuple[str, str] | None = None,
    preview: bool = False,
    error: str = "",
) -> ContentEditor:
    if kind not in content.KINDS or lang not in content.LANGS:
        abort(404)
    now = store.current(kind).get(("message", lang))
    subject, body = typed or current(kind, lang)
    header, text = "", ""
    if preview and not error:
        try:
            header, text = content.render(kind, subject, body, content.sample(kind))
        except ValueError as exc:
            error = str(exc)
    return ContentEditor(
        kind,
        lang,
        subject,
        body,
        now,
        store.history("message", lang, kind),
        content.FIELDS[kind],
        header,
        text,
        error,
    )


def install(app: Flask, conf_lang: str) -> None:
    from . import mailing_documents

    mailing_documents.install(app, conf_lang)

    @app.post("/administration/mailings/<kind>/content", endpoint="mailing_content_save")
    @guard.action("mailing.manage")
    def save(kind: str) -> Response | tuple[str, int]:
        refuse_foreign_origin()
        lang = request.form.get("tlang", "")
        if kind not in content.KINDS or lang not in content.LANGS:
            abort(404)
        action = request.form.get("action", "save")
        typed = (request.form.get("subject", ""), request.form.get("body", ""))
        try:
            if action == "preview":
                ed = editor(kind, lang, typed=typed, preview=True)
                return render_template(
                    "administration/content_editor.html",
                    ed=ed,
                    lang=ui_lang.request_lang(conf_lang),
                ), 400 if ed.error else 200
            reset = action == "reset"
            who = auth.current_account()
            store.save(
                "message",
                lang,
                None if reset else typed[1],
                subject=None if reset else typed[0],
                actor=who.login if who else "",
                kind=kind,
            )
        except (MailingTemplateInputError, ValueError) as exc:
            ed = editor(kind, lang, typed=typed, error=str(exc))
            return render_template(
                "administration/content_editor.html", ed=ed, lang=ui_lang.request_lang(conf_lang)
            ), 400
        except DbError:
            return redirect(
                administration.url(
                    TAB_MAILINGS,
                    kind="prescription" if kind == "document" else kind,
                    saved="failed",
                ),
                code=303,
            )
        return redirect(
            administration.url(
                TAB_MAILINGS,
                kind="prescription" if kind == "document" else kind,
                content=kind,
                clang=lang,
                saved="tpl_reset" if reset else "tpl_ok",
            ),
            code=303,
        )
