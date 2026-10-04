"""Экшн-планы в вебе: раздел действий УК и раздел партнёра (волна 2, D263–D274).

Два раздела, а не один с кнопками по ролям (D264): заслон стоит на раздел
целиком. `/actions` — только пространству УК (`hq_only` в реестре,
`before_request`), и каждый маршрут раздела ещё раз сверяет это сам: скрытие
пункта в панели — не защита, и забытый в реестре флаг не должен открывать
приём планов партнёру. `/plans` — партнёру: свои страны по охвату (D284),
загрузка версии. Скачать версию могут свои страны и УК — по охвату, чужой
файл отвечает тем же 404, что несуществующий.

Писем, сообщений в бот и уведомлений нет (правило владельца): партнёр видит
запрос на экране, который открывает сам.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Mapping
from datetime import date
from typing import Any
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from flask import Response as FlaskResponse
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import action_plans as plans
from src.db.config import load_action_plan_settings
from src.db.errors import ActionPlanError, DbError, StorageError
from src.domain.tenants import HQ_TENANT, canonical_tenant

from . import auth
from .config import Settings
from .origin import refuse_foreign_origin
from .sections import section
from .texts import lang_or_default, t

logger = logging.getLogger(__name__)

#: Запас тела запроса сверх файла: поля формы и рамки multipart.
FORM_OVERHEAD_BYTES = 64 * 1024

#: Очереди раздела УК: что ждёт приёмки и что просрочено (спека).
QUEUE_REVIEW = "review"
QUEUE_OVERDUE = "overdue"
QUEUES = (QUEUE_REVIEW, QUEUE_OVERDUE)

#: Тон метки состояния — классы `tag` из `forma`.
STATE_TONES = {
    plans.STATE_REQUESTED: "tag--neutral",
    plans.STATE_RETURNED: "tag--warn",
    plans.STATE_ON_REVIEW: "tag--accent",
    plans.STATE_ACCEPTED: "tag--ok",
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


def country_plans(code: str) -> tuple[tuple[plans.PlanRequest, ...], bool]:
    """Запросы страны для её экрана и известно ли это."""
    if not code:
        return (), True
    try:
        return plans.list_requests(reach=auth.current_reach(), country=code), True
    except DbError as exc:
        logger.warning("экшн-планы страны %s не прочитаны: %s", code, exc)
        return (), False


def default_due() -> date:
    """Срок по умолчанию для ручного запроса — та же настройка, что у автозапроса (D274)."""
    return plans.due_date(plans.today(), load_action_plan_settings().due_days)


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip()[:10])
    except ValueError:
        return None


def install(app: Flask, conf: Settings) -> None:
    """Повесить маршруты обоих разделов. Настройки читаются на сборке: мусор — отказ сразу."""
    max_bytes = load_action_plan_settings().max_bytes
    _install_hq(app, conf)
    _install_partner(app, conf, max_bytes=max_bytes)


def _lang(conf: Settings) -> str:
    return lang_or_default(request.args.get("lang"), fallback=conf.ui_lang)


def _common(lang: str) -> dict[str, Any]:
    return {
        "today": plans.today(),
        "state_tones": STATE_TONES,
        "actions_path": section("actions").path,
        "plans_path": section("plans").path,
        "registry_path": section("registry").path,
    }


def _require_hq() -> None:
    """Второй заслон раздела УК — на самом маршруте (первый — `before_request`)."""
    if not is_hq():
        abort(404)


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


# ── Раздел УК ───────────────────────────────────────────────────────────────


def _install_hq(app: Flask, conf: Settings) -> None:
    путь = section("actions").path

    @app.get(путь, endpoint="actions")
    def actions() -> str:
        _require_hq()
        lang = _lang(conf)
        страна = (request.args.get("country") or "").strip().upper()[:2]
        очередь = (request.args.get("queue") or "").strip()
        очередь = очередь if очередь in QUEUES else ""
        все = plans.list_requests(reach=auth.current_reach())
        сегодня = plans.today()
        страны = tuple(sorted({r.country for r in все if r.country}))
        в_стране = tuple(r for r in все if not страна or r.country == страна)
        на_приёмке = tuple(r for r in в_стране if r.status == plans.STATUS_ON_REVIEW)
        просрочены = tuple(r for r in в_стране if r.overdue(сегодня))
        строки = {QUEUE_REVIEW: на_приёмке, QUEUE_OVERDUE: просрочены}.get(очередь, в_стране)

        def отбор(**изменения: str) -> str:
            параметры = {"country": страна, "queue": очередь, "lang": lang, **изменения}
            живые = {к: з for к, з in параметры.items() if з}
            return url_for("actions") + (f"?{urlencode(живые)}" if живые else "")

        return render_template(
            "actions/index.html",
            rows=строки,
            countries=страны,
            country=страна,
            queue=очередь,
            on_review=len(на_приёмке),
            overdue=len(просрочены),
            total=len(в_стране),
            select_url=отбор,
            **_common(lang),
        )

    @app.get(f"{путь}/requests/<request_id>", endpoint="actions_request")
    def actions_request(request_id: str) -> str | tuple[str, int]:
        _require_hq()
        return _render_request(request_id, conf=conf, notice=None, failure=None)

    @app.post(f"{путь}/requests/<request_id>/review")
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
            return _render_request(
                request_id, conf=conf, notice=None, failure=t("plans.failed", lang, reason=exc)
            )
        notice = "plans.accepted" if вердикт == plans.VERDICT_ACCEPTED else "plans.returned"
        return _render_request(request_id, conf=conf, notice=t(notice, lang), failure=None)

    @app.post(f"{путь}/requests/<request_id>/due")
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
            return _render_request(
                request_id, conf=conf, notice=None, failure=t("plans.failed", lang, reason=exc)
            )
        return _render_request(request_id, conf=conf, notice=t("plans.due_set", lang), failure=None)

    @app.post(f"{путь}/request")
    def actions_new() -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        проверка = (request.form.get("inspection_id") or "").strip()
        срок = _parse_date(request.form.get("due") or "")
        try:
            if срок is None:
                raise ActionPlanError(t("plans.bad_date", lang))
            новый = plans.request_plan(проверка, actor=_actor(), due_on=срок)
        except ActionPlanError as exc:
            return render_template(
                "actions/refused.html",
                failure=t("plans.failed", lang, reason=exc),
                inspection_id=проверка,
                **_common(lang),
            ), 400
        return redirect(url_for("actions_request", request_id=новый, lang=lang), code=303)


def _render_request(
    request_id: str, *, conf: Settings, notice: str | None, failure: str | None
) -> str | tuple[str, int]:
    lang = _lang(conf)
    запрос = plans.get_request(request_id, reach=auth.current_reach())
    if запрос is None:
        return render_template("inspections/not_found.html"), 404
    return render_template(
        "actions/request.html",
        r=запрос,
        notice=notice,
        failure=failure,
        **_common(lang),
    )


# ── Раздел партнёра ────────────────────────────────────────────────────────


def _install_partner(app: Flask, conf: Settings, *, max_bytes: int) -> None:
    путь = section("plans").path

    @app.get(путь, endpoint="plans")
    def plans_index() -> Response | str:
        if is_hq():
            # У УК свой раздел (D264): здесь ему нечего загружать.
            return redirect(url_for("actions", lang=_lang(conf)), code=303)
        return _render_partner(conf, max_bytes=max_bytes, notice=None, failure=None)

    @app.post(f"{путь}/<request_id>/upload")
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
            return _render_partner(
                conf, max_bytes=max_bytes, notice=None, failure=t("plans.too_big", lang, mb=мб)
            ), 413
        if файл is None or not файл.filename:
            return _render_partner(
                conf, max_bytes=max_bytes, notice=None, failure=t("plans.no_file", lang)
            ), 400
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
            return _render_partner(
                conf,
                max_bytes=max_bytes,
                notice=None,
                failure=t("plans.failed", lang, reason=exc),
            ), 400
        except StorageError as exc:
            # Текст хранилища называет корзину и ключ — партнёру он ни к чему.
            logger.warning("файл плана к запросу %s не лёг в хранилище: %s", request_id, exc)
            return _render_partner(
                conf, max_bytes=max_bytes, notice=None, failure=t("plans.storage_down", lang)
            ), 503
        return _render_partner(
            conf,
            max_bytes=max_bytes,
            notice=t("plans.uploaded", lang, version=версия),
            failure=None,
        )

    @app.get(f"{путь}/files/<file_id>", endpoint="plan_file")
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
        ответ.headers["X-Content-Type-Options"] = "nosniff"
        ответ.headers["Cache-Control"] = "private, no-store"
        return ответ


def _render_partner(
    conf: Settings, *, max_bytes: int, notice: str | None, failure: str | None
) -> str:
    lang = _lang(conf)
    запросы = plans.list_requests(reach=auth.current_reach())
    return render_template(
        "plans/index.html",
        rows=запросы,
        max_mb=max_bytes // (1024 * 1024),
        notice=notice,
        failure=failure,
        **_common(lang),
    )
