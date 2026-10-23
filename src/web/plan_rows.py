"""Строки электронного плана в вебе: запись партнёра и вердикты УК (#1168, D613, D617, D618, D621).

Экран один — панель запроса во вкладке «Экшн-планы» (`action_plans.py`); здесь только
маршруты записи под ней. Партнёр (`plan.submit`) заполняет строки, отправляет план на
согласование и ведёт строки «Взяли в работу» → «Сделано». УК (`plan.manage`, и ещё раз
`_require_hq` на самом маршруте) принимает план или возвращает с комментарием,
подтверждает или возвращает строки и сдвигает начало отсчёта. Права и порядок переходов
держит база (миграция 0092); здесь — маршруты, разбор формы и текст отказа на языке
человека. Все записи — POST под проверкой происхождения. Уведомления внутри приложения
пишет сама запись (`plan_notify`); писем и сообщений в бот нет.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from flask import Flask, abort, request

from src.db import action_plans as plans
from src.db import plan_flow as flow
from src.db.errors import ActionPlanError, DbError
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import auth, guard, ui_lang
from .config import Settings
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

#: Ответ панели: (conf, id запроса, notice=, failure=, status=) — `action_plans._respond`.
Respond = Callable[..., Any]


def _is_hq() -> bool:
    return canonical_tenant(auth.current_tenant()) == HQ_TENANT


def _require_hq() -> None:
    """Второй заслон записей УК — на самом маршруте (первый — матрица прав)."""
    if not _is_hq():
        abort(404)


def _require_partner() -> None:
    """Запись партнёра: УК за партнёра не заполняет и не отмечает — права тоже в базе."""
    if _is_hq():
        abort(403)


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


def _field(name: str) -> str:
    return (request.form.get(name) or "").strip()


def _optional_date(raw: str, lang: str) -> date | None:
    """Пустое поле — даты нет; неразобранное — отказ с текстом, а не молчаливое «нет»."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise ActionPlanError(t("plans.bad_date", lang)) from None


def install(app: Flask, conf: Settings, *, respond: Respond) -> None:
    """Повесить маршруты записи строк. `respond` — ответ панели, общий со вкладкой."""
    путь = section("actions").path

    def lang() -> str:
        return ui_lang.request_lang(conf.ui_lang)

    def done(request_id: str, notice_key: str, **params: Any) -> Any:
        return respond(conf, request_id, notice=t(notice_key, lang(), **params))

    def refused(request_id: str, exc: ActionPlanError, status: int = 400) -> Any:
        return respond(
            conf, request_id, failure=t("plans.failed", lang(), reason=exc), status=status
        )

    # ── Партнёр ────────────────────────────────────────────────────────────

    @app.post(f"{путь}/requests/<request_id>/rows/<row_id>/save")
    @guard.action("plan.submit")
    def plan_row_save(request_id: str, row_id: str) -> Any:
        _require_partner()
        refuse_foreign_origin()
        try:
            flow.save_row(
                request_id,
                row_id,
                reach=auth.current_reach(),
                tenant=auth.current_tenant(),
                actor=_actor(),
                measure=_field("measure"),
                responsible=_field("responsible"),
                reason=_field("reason"),
                own_due=_optional_date(_field("own_due"), lang()),
            )
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, "plans.rows.saved")

    @app.post(f"{путь}/requests/<request_id>/submit")
    @guard.action("plan.submit")
    def plan_submit(request_id: str) -> Any:
        _require_partner()
        refuse_foreign_origin()
        try:
            flow.submit_plan(
                request_id,
                reach=auth.current_reach(),
                tenant=auth.current_tenant(),
                actor=_actor(),
            )
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, "plans.rows.submitted")

    def _partner_move(
        request_id: str, row_id: str, move: Callable[..., None], notice_key: str
    ) -> Any:
        _require_partner()
        refuse_foreign_origin()
        try:
            move(
                request_id,
                row_id,
                reach=auth.current_reach(),
                tenant=auth.current_tenant(),
                actor=_actor(),
            )
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, notice_key)

    @app.post(f"{путь}/requests/<request_id>/rows/<row_id>/start")
    @guard.action("plan.submit")
    def plan_row_start(request_id: str, row_id: str) -> Any:
        return _partner_move(request_id, row_id, flow.start_row, "plans.rows.started")

    @app.post(f"{путь}/requests/<request_id>/rows/<row_id>/done")
    @guard.action("plan.submit")
    def plan_row_done(request_id: str, row_id: str) -> Any:
        return _partner_move(request_id, row_id, flow.finish_row, "plans.rows.finished")

    # ── УК ─────────────────────────────────────────────────────────────────

    @app.post(f"{путь}/requests/<request_id>/accept")
    @guard.action("plan.manage")
    def plan_accept(request_id: str) -> Any:
        _require_hq()
        refuse_foreign_origin()
        try:
            flow.accept_plan(request_id, actor=_actor())
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, "plans.accepted")

    @app.post(f"{путь}/requests/<request_id>/return")
    @guard.action("plan.manage")
    def plan_return(request_id: str) -> Any:
        _require_hq()
        refuse_foreign_origin()
        try:
            flow.return_plan(request_id, actor=_actor(), comment=_field("comment"))
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, "plans.returned")

    @app.post(f"{путь}/requests/<request_id>/rows/<row_id>/confirm")
    @guard.action("plan.manage")
    def plan_row_confirm(request_id: str, row_id: str) -> Any:
        _require_hq()
        refuse_foreign_origin()
        try:
            flow.confirm_row(request_id, row_id, actor=_actor())
        except ActionPlanError as exc:
            return refused(request_id, exc)
        closed = _is_closed(request_id)
        return done(request_id, "plans.rows.confirmed_closed" if closed else "plans.rows.confirmed")

    @app.post(f"{путь}/requests/<request_id>/rows/<row_id>/reject")
    @guard.action("plan.manage")
    def plan_row_reject(request_id: str, row_id: str) -> Any:
        _require_hq()
        refuse_foreign_origin()
        try:
            flow.return_row(request_id, row_id, actor=_actor(), reason=_field("reason"))
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, "plans.rows.rejected")

    @app.post(f"{путь}/requests/<request_id>/count-from")
    @guard.action("plan.manage")
    def plan_count_from(request_id: str) -> Any:
        _require_hq()
        refuse_foreign_origin()
        try:
            начало = _optional_date(_field("count_from"), lang())
            if начало is None:
                raise ActionPlanError(t("plans.bad_date", lang()))
            flow.set_count_from(request_id, actor=_actor(), count_from=начало)
        except ActionPlanError as exc:
            return refused(request_id, exc)
        return done(request_id, "plans.count_from.set")


def _is_closed(request_id: str) -> bool:
    """План закрыт после подтверждения строки? Не прочитали — общее «подтверждена»."""
    try:
        item = plans.get_request(request_id, reach=auth.current_reach())
    except DbError as exc:
        logger.warning("запрос плана %s после вердикта не прочитан: %s", request_id, exc)
        return False
    return item is not None and item.status == plans.STATUS_CLOSED
