"""Экшн-планы в вебе: вкладка «Экшн-планы» раздела «Действия» (волна 2, D263–D274, D526).

Раздел один у УК и партнёра (D526): список и панель выбранного запроса — экран
`actions_screen`, здесь данные вкладки и записи. Что видит и может каждый,
решают охват и матрица прав, а не раздел: запросы читаются только в охвате
вошедшего (D284), приём, возврат, срок и запрос — `plan.manage`, и каждый такой
маршрут ещё раз сверяет УК сам (`_require_hq`): забытый флаг не должен открывать
приём планов партнёру; загрузка версии — `plan.submit`, партнёру. Скачать версию
могут свои страны и УК — по охвату, чужой файл отвечает тем же 404, что
несуществующий.

Писем, сообщений в бот и уведомлений нет (правило владельца): партнёр видит
запрос на экране, который открывает сам.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any

from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from flask import Response as FlaskResponse
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import action_plans as plans
from src.db import plan_rows as plan_rows_db
from src.db.config import load_action_plan_settings
from src.db.errors import ActionPlanError, DbError, StorageError
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import actions_screen, auth, guard, plan_rows, plan_template, review, ui_lang, view
from . import inspections as data
from .actions_columns import Block, RailItem, rail_codes, rail_form, sorted_rows
from .actions_screen import TAB_PLANS
from .config import Settings
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

#: Запас тела запроса сверх файла: поля формы и рамки multipart.
FORM_OVERHEAD_BYTES = 64 * 1024
#: Тип ответа шаблона плана (`plan_template`): книга Excel — открывается и в Google Таблицах.
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Тон метки состояния — классы `tag` из `forma`.
STATE_TONES = {
    plans.STATE_REQUESTED: "tag--neutral",
    plans.STATE_RETURNED: "tag--warn",
    plans.STATE_ON_REVIEW: "tag--accent",
    plans.STATE_ACCEPTED: "tag--ok",
    plans.STATE_IN_WORK: "tag--accent",
    plans.STATE_CLOSED: "tag--ok",
}


def is_hq() -> bool:
    """Вошедший из пространства УК."""
    return canonical_tenant(auth.current_tenant()) == HQ_TENANT


def today() -> date:
    """Сегодня для сроков и просрочки — то же, что у блока `db`."""
    return plans.today()


def card_plan(inspection_id: str) -> tuple[plans.PlanRequest | None, bool]:
    """Запрос по проверке для карточки и известно ли это (отказ базы карточку не роняет)."""
    try:
        return plans.request_of_inspection(inspection_id, reach=auth.current_reach()), True
    except DbError as exc:
        logger.warning("экшн-план проверки %s не прочитан: %s", inspection_id, exc)
        return None, False


def needs_plan(counts: Mapping[str, Any]) -> bool:
    """D2 или D3 в счётчиках движка — то же правило, что у автозапроса (D272)."""
    return plans.needs_action_plan(counts or {})


def unit_without_country(inspection_id: str) -> bool:
    """У точки проверки нет страны? Не прочитали — отметки нет, причина в журнале."""
    try:
        return plans.unit_country_missing(inspection_id, reach=auth.current_reach())
    except DbError as exc:
        logger.warning("страна точки проверки %s не прочитана: %s", inspection_id, exc)
        return False


EMPTY = plans.PlanList(rows=(), truncated=False)
#: Предел списка — для подписи «показаны первые N».
LIST_LIMIT = plans.LIST_LIMIT


def country_plans(code: str) -> tuple[plans.PlanList, plans.PlanList, bool]:
    """Открытые и принятые запросы страны для её экрана и известно ли это.

    Принятые читаются отдельно: итог плана экран страны показывает (критерий
    спеки), а в очередь они не попадают.
    """
    if not code:
        return EMPTY, EMPTY, True
    охват = auth.current_reach()
    try:
        открытые = plans.list_requests(reach=охват, country=code)
        принятые = plans.list_requests(reach=охват, country=code, accepted=True)
    except DbError as exc:
        logger.warning("экшн-планы страны %s не прочитаны: %s", code, exc)
        return EMPTY, EMPTY, False
    return открытые, принятые, True


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip()[:10])
    except ValueError:
        return None


def install(app: Flask, conf: Settings) -> None:
    """Повесить маршруты вкладки. Настройки читаются на сборке: мусор — отказ сразу."""
    max_bytes = load_action_plan_settings().max_bytes
    actions_screen.register(
        app,
        TAB_PLANS,
        actions_screen.Tab(
            screen=lambda lang: screen_context(lang),
            panel=lambda item_id, **outcome: panel_context(item_id, max_bytes=max_bytes, **outcome),
            missing=lambda: (render_template("inspections/not_found.html"), 404),
        ),
    )
    _install_hq(app, conf)
    _install_partner(app, conf, max_bytes=max_bytes)
    _install_template(app, conf)
    plan_rows.install(app, conf, respond=_respond)
    _install_legacy(app)


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def _files_path() -> str:
    return section("actions").path + "/plan-files"


def _require_hq() -> None:
    """Второй заслон записей УК — на самом маршруте (первый — матрица прав)."""
    if not is_hq():
        abort(404)


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


def _respond(
    conf: Settings,
    request_id: str,
    *,
    notice: str | None = None,
    failure: str | None = None,
    status: int = 200,
) -> str | tuple[str, int]:
    return actions_screen.respond(
        conf, TAB_PLANS, item_id=request_id, notice=notice, failure=failure, status=status
    )


# ── Данные вкладки ──────────────────────────────────────────────────────────


#: Блоки списка запросов в порядке показа: состояние, ключ заголовка.
_PLAN_BLOCKS = (
    (plans.STATE_ON_REVIEW, "plans.block.on_review"),
    (plans.STATE_IN_WORK, "plans.block.in_work"),
    (plans.STATE_RETURNED, "plans.block.returned"),
    (plans.STATE_REQUESTED, "plans.block.requested"),
)
#: Что показывает столбец у страны: ждут приёмки, ждут партнёра (запрошены и возвращены).
_PLAN_RAIL = (
    ((plans.STATE_ON_REVIEW,), "plans.rail.on_review"),
    ((plans.STATE_IN_WORK,), "plans.rail.in_work"),
    ((plans.STATE_REQUESTED, plans.STATE_RETURNED), "plans.rail.waiting"),
)


def _rail_item(code: str, rows: tuple[plans.PlanRequest, ...], today: date) -> RailItem:
    parts = tuple(
        (text, n) for states, text in _PLAN_RAIL if (n := sum(1 for r in rows if r.state in states))
    )
    return RailItem(code, parts, sum(1 for r in rows if r.overdue(today)))


def screen_context(lang: str) -> dict[str, Any]:
    """Список запросов — столбец стран и блоки по состоянию, одни у УК и партнёра (D526, D611)."""
    страна = (request.args.get("country") or "").strip().upper()[:2]
    принятые = request.args.get("accepted") == "1"
    reach = auth.current_reach()
    открытые = plans.list_requests(reach=reach, accepted=False)
    архив = plans.list_requests(reach=reach, accepted=True) if принятые else None
    сегодня = plans.today()
    все = открытые.rows
    страны = rail_codes(
        reach,
        [r.country for r in (*все, *(архив.rows if архив else ())) if r.country],
        страна,
        lang,
    )

    def в_стране(rows: tuple[plans.PlanRequest, ...]) -> tuple[plans.PlanRequest, ...]:
        return tuple(r for r in rows if not страна or r.country == страна)

    def отбор(**изменения: str) -> str:
        параметры: dict[str, Any] = {
            "tab": TAB_PLANS,
            "country": страна,
            "accepted": "1" if принятые else "",
            "lang": lang,
            **изменения,
        }
        return url_for("actions", **{к: з for к, з in параметры.items() if з})

    видимые = в_стране(все)
    принятые_в_стране = в_стране(архив.rows) if архив else ()
    блоки = tuple(
        Block(state, title, chosen_rows)
        for state, title in _PLAN_BLOCKS
        if (
            chosen_rows := sorted_rows(
                (r for r in видимые if r.state == state), today=сегодня, overdue_first=True
            )
        )
    )
    блоки += (
        Block("accepted", "plans.block.accepted", принятые_в_стране, len(принятые_в_стране))
        if архив
        else Block("accepted", "plans.block.accepted", (), None, отбор(accepted="1")),
    )
    столбец = (
        (
            _rail_item("", все, сегодня),
            *(_rail_item(c, tuple(r for r in все if r.country == c), сегодня) for c in страны),
        )
        if len(страны) > 1 or страна
        else ()
    )
    return {
        "rows": видимые,
        "rail": столбец,
        "rail_form": rail_form(
            "actions", {"tab": TAB_PLANS}, lang, {"accepted": "1" if принятые else ""}
        ),
        "blocks": блоки,
        "countries": страны,
        "country": страна,
        "empty_key": "actions.list.empty",
        "truncated": открытые.truncated,
        "truncated_key": "plans.truncated",
        "limit": plans.LIST_LIMIT,
        "total": len(видимые) + len(принятые_в_стране),
        "select_url": отбор,
        "archive_param": "accepted",
        "today": сегодня,
        "state_tones": STATE_TONES,
        "grade_tone": view.grade_tone,
    }


def panel_context(
    request_id: str,
    *,
    max_bytes: int,
    notice: str | None = None,
    failure: str | None = None,
    gmail: str = "",
) -> dict[str, Any]:
    """Панель запроса: сам запрос в охвате вошедшего и то, что на нём можно делать."""
    запрос = None
    не_прочитан = False
    try:
        запрос = plans.get_request(request_id, reach=auth.current_reach())
    except DbError as exc:
        logger.warning("запрос экшн-плана %s не прочитан: %s", request_id, exc)
        не_прочитан = True
    return {
        "item": запрос,
        "failed": не_прочитан,
        "notice": notice,
        "failure": failure,
        "gmail": "",
        "hq": is_hq(),
        "max_mb": max_bytes // (1024 * 1024),
        "focus_row": (request.args.get("row") or "").strip(),
        "row_limits": {
            "measure": plan_rows_db.MAX_MEASURE,
            "responsible": plan_rows_db.MAX_RESPONSIBLE,
            "reason": plan_rows_db.MAX_REASON,
        },
        "today": plans.today(),
        "state_tones": STATE_TONES,
        "grade_tone": view.grade_tone,
        "plan_files_path": _files_path(),
        "actions_path": section("actions").path,
        "registry_path": section("registry").path,
    }


# ── Запись УК ───────────────────────────────────────────────────────────────


def _install_hq(app: Flask, conf: Settings) -> None:
    путь = section("actions").path

    @app.post(f"{путь}/requests/<request_id>/review")
    @guard.action("plan.manage")
    def actions_review(request_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        вердикт = (request.form.get("verdict") or "").strip()
        try:
            plans.review(
                request_id,
                actor=_actor(),
                verdict=вердикт,
                comment=request.form.get("comment") or "",
            )
        except ActionPlanError as exc:
            return _respond(conf, request_id, failure=t("plans.failed", lang, reason=exc))
        notice = "plans.accepted" if вердикт == plans.VERDICT_ACCEPTED else "plans.returned"
        return _respond(conf, request_id, notice=t(notice, lang))

    @app.post(f"{путь}/requests/<request_id>/due")
    @guard.action("plan.manage")
    def actions_due(request_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        срок = _parse_date(request.form.get("due") or "")
        try:
            if срок is None:
                raise ActionPlanError(t("plans.bad_date", lang))
            plans.set_due(request_id, actor=_actor(), due_on=срок)
        except ActionPlanError as exc:
            return _respond(conf, request_id, failure=t("plans.failed", lang, reason=exc))
        return _respond(conf, request_id, notice=t("plans.due_set", lang))

    @app.post(f"{путь}/request")
    @guard.action("plan.manage")
    def actions_new() -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        проверка = (request.form.get("inspection_id") or "").strip()
        начало_raw = (request.form.get("count_from") or "").strip()
        начало = _parse_date(начало_raw)
        срок_raw = (request.form.get("due") or "").strip()
        срок = _parse_date(срок_raw)
        try:
            if (начало_raw and начало is None) or (срок_raw and срок is None):
                raise ActionPlanError(t("plans.bad_date", lang))
            новый = plans.request_plan(проверка, actor=_actor(), due_on=срок, count_from=начало)
        except ActionPlanError as exc:
            return render_template(
                "actions/refused.html",
                failure=t("plans.failed", lang, reason=exc),
                inspection_id=проверка,
                registry_path=section("registry").path,
            ), 400
        return redirect(actions_screen.panel_link(TAB_PLANS, новый, lang=lang), code=303)


# ── Запись партнёра и файлы ─────────────────────────────────────────────────


def _install_partner(app: Flask, conf: Settings, *, max_bytes: int) -> None:
    путь = section("actions").path

    @app.post(f"{путь}/requests/<request_id>/upload")
    @guard.action("plan.submit")
    def plans_upload(request_id: str) -> str | tuple[str, int]:
        if is_hq():
            return render_template("users/forbidden.html"), 403
        refuse_foreign_origin()
        lang = _lang(conf)
        # Предел — только этому маршруту (D269): остальные формы держат свой.
        request.max_content_length = max_bytes + FORM_OVERHEAD_BYTES
        мб = max_bytes // (1024 * 1024)
        try:
            файл = request.files.get("file")
        except RequestEntityTooLarge:
            return _respond(conf, request_id, failure=t("plans.too_big", lang, mb=мб), status=413)
        if файл is None or not файл.filename:
            return _respond(conf, request_id, failure=t("plans.no_file", lang), status=400)
        try:
            версия = plans.upload_version(
                request_id,
                reach=auth.current_reach(),
                tenant=auth.current_tenant(),
                actor=_actor(),
                file_name=файл.filename,
                content_type=файл.mimetype or "",
                data=файл.read(max_bytes + 1),
                max_bytes=max_bytes,
            )
        except ActionPlanError as exc:
            return _respond(
                conf, request_id, failure=t("plans.failed", lang, reason=exc), status=400
            )
        except StorageError as exc:
            # Текст хранилища называет корзину и ключ — партнёру он ни к чему.
            logger.warning("файл плана к запросу %s не лёг в хранилище: %s", request_id, exc)
            return _respond(conf, request_id, failure=t("plans.storage_down", lang), status=503)
        return _respond(conf, request_id, notice=t("plans.uploaded", lang, version=версия))

    @app.get(f"{путь}/plan-files/<file_id>", endpoint="plan_file")
    def plan_file(file_id: str) -> FlaskResponse | tuple[str, int]:
        """Версия плана — вложением, своей стране и УК. Чужой файл — тот же 404."""
        ссылка = plans.file_for_download(file_id, reach=auth.current_reach())
        if ссылка is None:
            return "", 404
        try:
            байты = plans.fetch_file(ссылка)
        except (DbError, StorageError) as exc:
            logger.warning("файл плана %s не выдан: %s", file_id, exc)
            return "", 503
        # Любой формат (D267) отдаётся только вложением и без угадывания типа:
        # HTML, открытый как страница админки, — хранимый XSS.
        ответ = send_file(
            io.BytesIO(байты),
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=ссылка.file_name,
        )
        # `nosniff` ставит общий крючок (`src/web/security_headers.py`).
        ответ.headers["Cache-Control"] = "private, no-store"
        return ответ


# ── Шаблон плана (#976) ─────────────────────────────────────────────────────


def _install_template(app: Flask, conf: Settings) -> None:
    путь = section("actions").path

    @app.get(f"{путь}/requests/<request_id>/template.xlsx", endpoint="plan_template")
    def plan_template_file(request_id: str) -> FlaskResponse | tuple[str, int]:
        """Шаблон — тем, кому виден запрос: партнёру своей страны и УК; чужой — 404."""
        lang = _lang(conf)
        охват = auth.current_reach()
        try:
            запрос = plans.get_request(request_id, reach=охват)
            деталь = data.load_card(запрос.inspection_id, reach=охват) if запрос else None
        except DbError as exc:
            logger.warning("шаблон плана к запросу %s не собран: %s", request_id, exc)
            return t("plans.tpl.failed", lang), 503
        if запрос is None or деталь is None:
            return "", 404
        лист = review.load_sheet(деталь.inspection, lang=lang)
        зоны = {z.code: z.name for z in лист.zones} if лист else {}
        метки = {p.code: p.label for p in лист.picks} if лист else {}
        ответ = send_file(
            io.BytesIO(plan_template.build(запрос, деталь.findings, зоны, lang, метки)),
            mimetype=XLSX_MIME,
            as_attachment=True,
            download_name=plan_template.file_name(запрос),
        )
        ответ.headers["Cache-Control"] = "private, no-store"
        return ответ


# ── Старые адреса ───────────────────────────────────────────────────────────


def _install_legacy(app: Flask) -> None:
    """Адреса до D526 переадресуют в «Действия»: закладки и ссылки не ломаются."""
    путь = section("actions").path

    @app.get("/plans", endpoint="plans")
    def plans_index() -> Response:
        return actions_screen.redirect_to_screen(TAB_PLANS)

    @app.get(f"{путь}/requests/<request_id>", endpoint="actions_request")
    def actions_request(request_id: str) -> Response:
        return actions_screen.redirect_to_screen(TAB_PLANS, request_id)

    @app.get("/plans/files/<file_id>", endpoint="plan_file_legacy")
    def plan_file_legacy(file_id: str) -> Response:
        return redirect(url_for("plan_file", file_id=file_id), code=303)
