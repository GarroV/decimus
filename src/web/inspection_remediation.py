"""Чек-лист исправлений в карточке принятой проверки и решения проверяющего."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from flask import Flask, abort, redirect, request, url_for
from werkzeug.wrappers import Response

from src.db import inspection_followup as evidence
from src.db import inspection_remediation as store
from src.db.errors import DbError

from . import auth, guard, inspections, ui_lang
from .config import Settings
from .origin import refuse_foreign_origin
from .texts import t

log = logging.getLogger(__name__)


def card_context(detail: Any) -> dict[str, Any]:
    """Состояния исходных находок; материалы и история только выбранного пункта."""
    head = detail.inspection
    if head.on_review:
        return {"repairs_visible": False, "repairs": {}}
    reach = auth.current_reach()
    admin = inspections.sees_retracted(reach)
    try:
        states = store.states(head.id, reach=reach, as_admin=admin)
        items = [f for f in detail.findings if f.id in states]
        chosen = request.values.get("repair") or (items[0].id if items else None)
        active = next((f for f in items if f.id == chosen), None)
        page = evidence.Page()
        history = store.EventPage()
        if active:
            page = evidence.list_entries(
                head.id,
                reach=reach,
                finding_id=active.id,
                before=request.args.get("repair_before"),
                as_admin=admin,
            )
            cursor = request.args.get("event_before", type=int)
            history = store.events(head.id, active.id, reach=reach, as_admin=admin, before=cursor)
    except (DbError, ValueError):
        log.warning("Не прочитаны исправления проверки %s", head.id)
        return {"repairs_visible": True, "repairs_known": False, "repairs": {}}
    return {
        "repairs_visible": True,
        "repairs_known": True,
        "repairs": states,
        "repair_items": items,
        "repair_active": active,
        "repair_page": page,
        "repair_history": history,
        "repairs_closed": sum(s.status == "confirmed" for s in states.values()),
        "repair_may_add": not head.retracted and guard.may("inspection.followup"),
        "repair_may_review": not head.retracted
        and guard.may("inspection.remediation.review", head.tenant_code),
    }


def install(
    app: Flask, conf: Settings, *, render_card: Callable[[str], str | tuple[str, int]]
) -> None:
    def change(
        inspection_id: str, finding_id: str, decision: str
    ) -> Response | str | tuple[str, int]:
        refuse_foreign_origin()
        lang = ui_lang.request_lang(conf.ui_lang)
        detail = inspections.load_card(inspection_id, reach=auth.current_reach())
        if detail is None:
            abort(404)
        if decision != "submit":
            refusal = guard.permit("inspection.remediation.review", detail.inspection.tenant_code)
            if refusal is not None:
                return refusal
        if detail.inspection.on_review or detail.inspection.retracted:
            return t("work.error.inspection", lang), 409
        account = auth.current_account()
        if account is None:
            abort(403)
        try:
            revision = int(request.form.get("revision", ""))
            store.transition(
                inspection_id,
                finding_id,
                reach=auth.current_reach(),
                actor=(
                    (account.display_name or "").strip()
                    or (account.email or "").strip()
                    or account.login
                )[:200],
                action=decision,
                revision=revision,
                reason=request.form.get("reason", ""),
            )
        except store.RemediationRefused as exc:
            return t("repair.error." + str(exc), lang), 409
        except ValueError:
            return t("repair.error.conflict", lang), 409
        except DbError:
            log.warning("Не сохранено решение по исправлению %s/%s", inspection_id, finding_id)
            return t("work.error.save", lang), 503
        if request.headers.get("X-Panel") == "1":
            return render_card(inspection_id)
        return redirect(
            url_for("card", inspection_id=inspection_id, lang=lang, repair=finding_id)
            + "#repair-"
            + finding_id,
            code=303,
        )

    @app.post("/inspections/<inspection_id>/repairs/<finding_id>/submit")
    @guard.action("inspection.followup")
    def inspection_repair_submit(
        inspection_id: str, finding_id: str
    ) -> Response | str | tuple[str, int]:
        return change(inspection_id, finding_id, "submit")

    @app.post("/inspections/<inspection_id>/repairs/<finding_id>/review/<decision>")
    @guard.action("inspection.remediation.review", object_in_route=True)
    def inspection_repair_review(
        inspection_id: str, finding_id: str, decision: str
    ) -> Response | str | tuple[str, int]:
        if decision not in {"confirm", "return", "reopen"}:
            abort(404)
        return change(inspection_id, finding_id, decision)
