"""Файл «туда и обратно» электронного плана на экране (#1168, шаг 3).

Выгрузка книги, итог загрузки и выбор при конфликте. Книгу и разбор делает `plan_sheet`,
сверку и запись — блок `db` (`plan_file`, `plan_flow.apply_file_rows`): здесь маршрут записи
выбора, чтение файла из версий и то, что показывает панель запроса (`FileResult`).

Загрузка — маршрут `plans_upload` в `action_plans.py` (общий с файловым путём), он зовёт
отсюда `read_sheet` до записи версии и `after_upload` после неё. Ничего не уходит человеку:
итог виден на экране, который партнёр открыл сам.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Flask, abort, request

from src.db import action_plans as plans
from src.db import plan_flow as flow
from src.db.errors import ActionPlanError, DbError, StorageError
from src.db.plan_file import FileApplied
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import auth, guard, plan_sheet, ui_lang
from .config import Settings
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

#: Что показывает панель после загрузки файла.
KIND_APPLIED = "applied"
KIND_CONFLICT = "conflict"
KIND_UNPARSED = "unparsed"
KIND_OTHER_PLAN = "other_plan"

#: Ответ панели: (conf, id запроса, notice=, failure=, status=, file_result=).
Respond = Callable[..., Any]

#: Выбор по строке при конфликте («screen» — оставить экран, ничего не берётся) и режимы формы.
PICK_FILE = "file"
MODE_PICK = "pick"
MODE_FILE = "file"
MODE_SCREEN = "screen"
PICK_PREFIX = "pick_"


@dataclass(frozen=True)
class FileResult:
    """Итог загрузки файла для панели: что прочли, что легло, где разошлось."""

    kind: str
    applied: FileApplied | None = None
    #: Версия файла, по которой выбирают при конфликте, и ревизия, на которой показана разница.
    file_id: str = ""
    revision: int = 0


def read_sheet(
    item: plans.PlanRequest | None, request_id: str, data: bytes
) -> tuple[plan_sheet.ParsedSheet | None, str | None]:
    """Разобрать загруженный файл электронного плана: `(книга, код причины неразбора)`.

    Файловому плану (и запросу вне охвата) книга не нужна — `(None, None)`. Файл другого
    плана разбору не подлежит: его id строк чужие, и принимать их за свои незачем.
    """
    if item is None or not item.electronic:
        return None, None
    try:
        sheet = plan_sheet.parse(data)
    except plan_sheet.SheetError as exc:
        return None, exc.code
    if sheet.request_id != request_id.strip().lower():
        return None, plan_sheet.ERR_OTHER_PLAN
    return sheet, None


def after_upload(
    request_id: str, version: int, sheet: plan_sheet.ParsedSheet | None, error: str | None
) -> FileResult | None:
    """Что делать после того, как версия файла легла: строки в план или пометка «не разобран».

    Ошибка записи строк (план уже ушёл на согласование и т. п.) — `ActionPlanError` вызывающему:
    версия остаётся в истории, строки нет.
    """
    if sheet is None:
        if error is None:
            return None
        return FileResult(KIND_OTHER_PLAN if error == plan_sheet.ERR_OTHER_PLAN else KIND_UNPARSED)
    applied = flow.apply_file_rows(
        request_id,
        reach=auth.current_reach(),
        tenant=auth.current_tenant(),
        actor=_actor(),
        file_rows=sheet.rows,
        expected_revision=sheet.revision,
    )
    if not applied.conflict:
        return FileResult(KIND_APPLIED, applied)
    return FileResult(
        KIND_CONFLICT,
        applied,
        file_id=_file_id(request_id, version),
        revision=applied.revision,
    )


def _file_id(request_id: str, version: int) -> str:
    """Id версии файла по её номеру — форма выбора читает файл из хранилища по нему."""
    try:
        item = plans.get_request(request_id, reach=auth.current_reach())
    except DbError as exc:
        logger.warning("запрос плана %s после загрузки не прочитан: %s", request_id, exc)
        return ""
    return next((f.id for f in (item.files if item else ()) if f.version == version), "")


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


def _is_hq() -> bool:
    return canonical_tenant(auth.current_tenant()) == HQ_TENANT


def _stored_sheet(file_id: str, request_id: str) -> plan_sheet.ParsedSheet | None:
    """Файл версии из хранилища, разобранный заново: форме выбора верят хранилищу, не полям."""
    ref = plans.file_for_download(file_id, reach=auth.current_reach())
    if ref is None:
        return None
    data = plans.fetch_file(ref)
    sheet, _error = read_sheet(
        plans.get_request(request_id, reach=auth.current_reach()), request_id, data
    )
    return sheet


def _revision(raw: str) -> int | None:
    return int(raw) if raw.isdigit() and len(raw) < 10 else None


def install(app: Flask, conf: Settings, *, respond: Respond) -> None:
    """Повесить маршрут выбора при конфликте. `respond` — ответ панели, общий со вкладкой."""
    путь = section("actions").path

    def lang() -> str:
        return ui_lang.request_lang(conf.ui_lang)

    def failed(request_id: str, key: str, status: int = 400, **params: Any) -> Any:
        return respond(conf, request_id, failure=t(key, lang(), **params), status=status)

    @app.post(f"{путь}/requests/<request_id>/file/apply")
    @guard.action("plan.submit")
    def plan_file_apply(request_id: str) -> Any:
        if _is_hq():
            abort(403)
        refuse_foreign_origin()
        mode = (request.form.get("mode") or "").strip()
        if mode == MODE_SCREEN:
            return respond(conf, request_id, notice=t("plans.file.kept_screen", lang()))
        seen = _revision((request.form.get("revision") or "").strip())
        if mode not in (MODE_FILE, MODE_PICK) or seen is None:
            return failed(request_id, "plans.file.failed")
        try:
            sheet = _stored_sheet((request.form.get("file") or "").strip(), request_id)
        except (DbError, StorageError) as exc:
            logger.warning("файл плана к запросу %s для выбора не прочитан: %s", request_id, exc)
            return failed(request_id, "plans.file.failed", 503)
        if sheet is None:
            return failed(request_id, "plans.file.gone")
        take = None
        if mode == MODE_PICK:
            take = frozenset(
                name.removeprefix(PICK_PREFIX)
                for name, value in request.form.items()
                if name.startswith(PICK_PREFIX) and value == PICK_FILE
            )
        try:
            applied = flow.apply_file_rows(
                request_id,
                reach=auth.current_reach(),
                tenant=auth.current_tenant(),
                actor=_actor(),
                file_rows=sheet.rows,
                expected_revision=seen,
                take=take,
            )
        except ActionPlanError as exc:
            return failed(request_id, "plans.failed", reason=exc)
        if applied.conflict:
            # Пока выбирали, план поменяли ещё раз: разницу показывают заново.
            return respond(
                conf,
                request_id,
                failure=t("plans.file.stale", lang()),
                file_result=FileResult(
                    KIND_CONFLICT,
                    applied,
                    file_id=(request.form.get("file") or "").strip(),
                    revision=applied.revision,
                ),
            )
        return respond(
            conf,
            request_id,
            notice=t("plans.file.resolved", lang(), n=applied.written),
            file_result=FileResult(KIND_APPLIED, applied),
        )
