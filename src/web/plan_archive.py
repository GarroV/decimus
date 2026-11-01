"""Read-only administration archive for the paused electronic action-plan workflow."""

from __future__ import annotations

import logging

from flask import Response, abort, make_response, render_template, request

from src.db import action_plans
from src.db.errors import DbError

from . import administration, auth, guard, ui_lang

log = logging.getLogger(__name__)


def show(conf_lang: str) -> Response:
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
            **administration.nav("plans"),
        )
    )
