"""Read-only administration archive for the paused electronic action-plan workflow."""

from __future__ import annotations

import logging

from flask import Flask, Response, abort, g, make_response, redirect, render_template, request

from src.db import action_plans, service_settings
from src.db.errors import DbError
from src.domain.features import action_plan_state

from . import administration, auth, guard, ui_lang
from .origin import refuse_foreign_origin
from .sections import section

log = logging.getLogger(__name__)


def show(conf_lang: str, *, save_failed: bool = False) -> Response:
    """Only administrators read existing plans; no state transitions live here."""
    if not guard.may("plan.archive"):
        abort(404)
    ui_lang.request_lang(conf_lang)
    failed = False
    rows: tuple[action_plans.PlanRequest, ...] = ()
    selected: action_plans.PlanRequest | None = None
    try:
        reach = auth.current_reach()
        active = action_plans.list_requests(reach=reach)
        accepted = action_plans.list_requests(reach=reach, accepted=True)
        rows = active.rows + accepted.rows
        ident = request.args.get("id", "").strip()[:64]
        if ident:
            selected = action_plans.get_request(ident, reach=reach)
            if selected is None:
                abort(404)
    except DbError:
        log.warning("Action-plan archive could not be read", exc_info=True)
        failed = True
    return make_response(
        render_template(
            "administration/plans.html",
            rows=rows,
            selected=selected,
            failed=failed,
            feature=action_plan_state(),
            outcome=request.args.get("saved", ""),
            save_failed=save_failed,
            **administration.nav("plans"),
        )
    )


def install(app: Flask, conf_lang: str) -> None:
    """Only HQ administrators can change the operational switch, even while OFF."""

    @app.post(section("administration").path + "/plans/settings", endpoint="action_plan_setting")
    @guard.action("service.settings")
    def save() -> Response:
        refuse_foreign_origin()
        value = request.form.get("enabled")
        if value not in {"0", "1"}:
            abort(400)
        g.journal_target = f"action_plans_enabled={value}"
        account = auth.current_account()
        if account is None:
            abort(403)
        try:
            service_settings.set_action_plans(value == "1", actor=account.login)
        except DbError:
            log.warning("Action-plan setting could not be saved")
            # A failed write is not a success redirect; action_journal records 503.
            return make_response(show(conf_lang, save_failed=True), 503)
        return make_response(redirect(administration.url("plans", saved="ok"), code=303))
