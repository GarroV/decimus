"""Предписания в вебе: раздел УК и раздел партнёра (волна 3, D266, D270, D275).

`/actions/prescriptions` — сотрудник УК составляет предписание, кладёт письмо
черновиком в свою почту Gmail и закрывает предписание с комментарием. Раздел
закрыт не-УК дважды: `hq_only` раздела «Действия» (`before_request`) и
`_require_hq` на каждом маршруте. `/prescriptions` — партнёр: свои страны по
охвату (D284), ответ комментарием и файлом. Файл ответа скачивают своя страна
и УК; чужой отвечает тем же 404, что несуществующий.

**Система ничего не отправляет.** Письмо ложится в черновики почты того, кто
нажал кнопку (`google_mail.create_draft`), и уходит его рукой. Никаких
сообщений партнёру от имени системы: он узнаёт о предписании из этого письма
и на своём экране.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any
from urllib.parse import urlencode

from flask import Flask, abort, current_app, redirect, render_template, request, send_file, url_for
from flask import Response as FlaskResponse
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import prescriptions as rx
from src.db import prescriptions_write as rxw
from src.db.config import load_action_plan_settings
from src.db.errors import DbError, IssuedDraftLostError, PrescriptionError, StorageError

from . import auth
from . import country as country_data
from .action_plans import FORM_OVERHEAD_BYTES, is_hq
from .config import Settings
from .geo_names import country_title
from .google_mail import GoogleMailError, create_draft
from .letter_draft import MAIL_CONSENT_KEY, MAIL_RETURNS_KEY, MailReturn
from .letter_markup import from_plain
from .origin import refuse_foreign_origin
from .sections import section
from .texts import lang_or_default, t

logger = logging.getLogger(__name__)

#: Вид похода за почтовым согласием (кука `letter_draft`).
MAIL_KIND = "prescription"

#: Очереди раздела УК над списком.
QUEUE_OVERDUE = "overdue"
QUEUE_REPLIED = "replied"
QUEUE_DRAFTS = "drafts"
QUEUES = (QUEUE_OVERDUE, QUEUE_REPLIED, QUEUE_DRAFTS)

#: Исходы похода в Gmail, которые экран умеет назвать словами.
GMAIL_OUTCOMES = ("ok", "failed", "denied", "unavailable", "lost")

#: Тон метки состояния — классы `tag` из `forma`.
STATE_TONES = {
    rx.STATE_DRAFT: "tag--neutral",
    rx.STATE_ACTIVE: "tag--accent",
    rx.STATE_OVERDUE: "tag--err",
    rx.STATE_CLOSED: "tag--ok",
}

EMPTY = rx.PrescriptionList(rows=(), truncated=False)


def _lang(conf: Settings) -> str:
    return lang_or_default(request.args.get("lang"), fallback=conf.ui_lang)


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


def _require_hq() -> None:
    """Второй заслон раздела УК — на самом маршруте (первый — `before_request`)."""
    if not is_hq():
        abort(404)


def _not_found() -> tuple[str, int]:
    """Чужое, черновое для партнёра и несуществующее — один ответ, но про предписание."""
    назад = section("actions").path + "/prescriptions" if is_hq() else section("orders").path
    return render_template("prescriptions/not_found.html", back=назад), 404


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip()[:10])
    except ValueError:
        return None


def _common() -> dict[str, Any]:
    return {
        "today": rx.today(),
        "rx_tones": STATE_TONES,
        "rx_hq_path": section("actions").path + "/prescriptions",
        "rx_partner_path": section("orders").path,
        "actions_path": section("actions").path,
        "registry_path": section("registry").path,
    }


def country_prescriptions(code: str) -> tuple[rx.PrescriptionList, bool]:
    """Предписания страны для её экрана и известно ли это (отказ базы экран не роняет)."""
    if not code:
        return EMPTY, True
    try:
        return rx.country_prescriptions(code, reach=auth.current_reach()), True
    except DbError as exc:
        logger.warning("предписания страны %s не прочитаны: %s", code, exc)
        return EMPTY, False


def country_block(code: str) -> dict[str, Any]:
    """Всё, что нужно блоку «Предписания» экрана страны."""
    список, известны = country_prescriptions(code)
    уК = is_hq()
    return {
        "rx_rows": список.rows,
        "rx_truncated": список.truncated,
        "rx_limit": rx.LIST_LIMIT,
        "rx_known": известны,
        "rx_act_hq": уК,
        "today_rx": rx.today(),
        "rx_tones": STATE_TONES,
        "rx_hq_path": section("actions").path + "/prescriptions",
        "rx_partner_path": section("orders").path,
    }


def install(app: Flask, conf: Settings) -> None:
    """Повесить маршруты обоих разделов и возврат из похода в Gmail."""
    max_bytes = load_action_plan_settings().max_bytes
    _install_hq(app, conf)
    _install_partner(app, conf, max_bytes=max_bytes)
    app.extensions.setdefault(MAIL_RETURNS_KEY, {})[MAIL_KIND] = MailReturn(
        back=_back_from_gmail, finish=_finish_gmail
    )


# ── Раздел УК ───────────────────────────────────────────────────────────────


def _draft_from_form(country: str) -> rx.Draft:
    срок = _parse_date(request.form.get("due") or "")
    if срок is None:
        raise PrescriptionError(t("rx.bad_date", request.args.get("lang") or "ru"))
    return rx.Draft(
        country=country,
        due_on=срок,
        recipients=request.form.get("recipients") or "",
        subject=request.form.get("subject") or "",
        body=request.form.get("body") or "",
        unit_ids=tuple(request.form.getlist("unit")),
        inspection_ids=tuple(request.form.getlist("inspection")),
    )


def _install_hq(app: Flask, conf: Settings) -> None:
    путь = section("actions").path + "/prescriptions"

    @app.get(путь, endpoint="rx_list")
    def rx_list() -> str:
        _require_hq()
        return _render_list(conf)

    @app.get(f"{путь}/new", endpoint="rx_new")
    def rx_new() -> str:
        _require_hq()
        lang = _lang(conf)
        страна = country_data.normalize_code(request.args.get("country") or "")
        return _render_form(
            lang=lang, country=страна, current=None, values=_defaults(страна, lang), failure=None
        )

    @app.post(путь, endpoint="rx_create")
    def rx_create() -> Response | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        страна = country_data.normalize_code(request.form.get("country") or "")
        try:
            ident = rxw.create_draft(_draft_from_form(страна), actor=_actor())
        except PrescriptionError as exc:
            return _render_form(
                lang=lang,
                country=страна,
                current=None,
                values=_form_values(),
                failure=t("rx.failed", lang, reason=exc),
            ), 400
        return _after_save(ident, lang)

    @app.get(f"{путь}/<prescription_id>", endpoint="rx_view")
    def rx_view(prescription_id: str) -> str | tuple[str, int]:
        _require_hq()
        return _render_card(prescription_id, conf=conf, notice=None, failure=None)

    @app.get(f"{путь}/<prescription_id>/edit", endpoint="rx_edit")
    def rx_edit(prescription_id: str) -> Response | str | tuple[str, int]:
        _require_hq()
        lang = _lang(conf)
        текущее = rx.get_prescription(prescription_id, reach=auth.current_reach())
        if текущее is None:
            return _not_found()
        if текущее.status != rx.STATUS_DRAFT:
            return redirect(url_for("rx_view", prescription_id=текущее.id, lang=lang), code=303)
        return _render_form(
            lang=lang,
            country=текущее.country,
            current=текущее,
            values=_values_of(текущее),
            failure=None,
        )

    @app.post(f"{путь}/<prescription_id>/edit", endpoint="rx_update")
    def rx_update(prescription_id: str) -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        текущее = rx.get_prescription(prescription_id, reach=auth.current_reach())
        if текущее is None:
            return _not_found()
        try:
            rxw.update_draft(текущее.id, _draft_from_form(текущее.country), actor=_actor())
        except PrescriptionError as exc:
            return _render_form(
                lang=lang,
                country=текущее.country,
                current=текущее,
                values=_form_values(),
                failure=t("rx.failed", lang, reason=exc),
            ), 400
        return _after_save(текущее.id, lang)

    @app.post(f"{путь}/<prescription_id>/send", endpoint="rx_send")
    def rx_send(prescription_id: str) -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        текущее = rx.get_prescription(prescription_id, reach=auth.current_reach())
        if текущее is None:
            return _not_found()
        return _go_to_gmail(текущее.id, _lang(conf))

    @app.post(f"{путь}/<prescription_id>/close", endpoint="rx_close")
    def rx_close(prescription_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        try:
            rxw.close(prescription_id, actor=_actor(), comment=request.form.get("comment") or "")
        except PrescriptionError as exc:
            return _render_card(
                prescription_id, conf=conf, notice=None, failure=t("rx.failed", lang, reason=exc)
            )
        return _render_card(prescription_id, conf=conf, notice=t("rx.closed", lang), failure=None)


def _after_save(ident: str, lang: str) -> Response:
    """После сохранения: на карточку — или сразу к Google, если просили положить в Gmail."""
    if request.form.get("then") == "send":
        return _go_to_gmail(ident, lang)
    return redirect(url_for("rx_view", prescription_id=ident, lang=lang, saved="1"), code=303)


def _go_to_gmail(ident: str, lang: str) -> Response:
    начать: Callable[[str, str, str], Response | None] = current_app.extensions[MAIL_CONSENT_KEY]
    поход = начать(MAIL_KIND, ident, lang)
    if поход is None:
        # Законная настройка стенда: без реквизитов Google черновика нет, и
        # предписание остаётся черновиком — экран говорит это словами.
        return _back_from_gmail(ident, lang, "unavailable")
    return поход


def _back_from_gmail(ident: str, lang: str, outcome: str) -> Response:
    return redirect(url_for("rx_view", prescription_id=ident, lang=lang, gmail=outcome), code=303)


def _finish_gmail(ident: str, lang: str, token: Callable[[], str]) -> Response:
    """Возврат от Google: положить черновик и в той же транзакции отметить «действует»."""
    if not is_hq():
        # Возврат — общий адрес `/auth/google/mail`, раздел УК его не прикрывает.
        abort(404)
    try:
        доступ = token()
    except GoogleMailError as exc:
        logger.warning("предписание %s: доступ к почте не получен: %s", ident, exc)
        return _back_from_gmail(ident, lang, "failed")

    def положить(предписание: rx.Prescription) -> None:
        create_draft(
            доступ,
            to=предписание.recipients,
            subject=предписание.subject,
            body=from_plain(предписание.body),
        )

    try:
        rxw.issue(ident, actor=_actor(), put_draft=положить)
    except IssuedDraftLostError:
        return _back_from_gmail(ident, lang, "lost")
    except (PrescriptionError, GoogleMailError) as exc:
        logger.warning("предписание %s не отправлено: %s", ident, exc)
        return _back_from_gmail(ident, lang, "failed")
    return _back_from_gmail(ident, lang, "ok")


def _defaults(country: str, lang: str) -> dict[str, Any]:
    """Пустая форма: адресаты страны из памяти (D275), тема по стране."""
    адресаты = ""
    if country:
        try:
            адресаты = rx.remembered_recipients(country)
        except PrescriptionError as exc:
            logger.warning("адресаты страны %s не прочитаны: %s", country, exc)
    return {
        "recipients": адресаты,
        "subject": t(
            "rx.form.subject_default", lang, country=country_title(country, lang) or country
        )
        if country
        else "",
        "body": "",
        "due": "",
        "units": (),
        "inspections": (),
    }


def _form_values() -> dict[str, Any]:
    return {
        "recipients": request.form.get("recipients") or "",
        "subject": request.form.get("subject") or "",
        "body": request.form.get("body") or "",
        "due": request.form.get("due") or "",
        "units": tuple(request.form.getlist("unit")),
        "inspections": tuple(request.form.getlist("inspection")),
    }


def _values_of(p: rx.Prescription) -> dict[str, Any]:
    return {
        "recipients": p.recipients,
        "subject": p.subject,
        "body": p.body,
        "due": p.due_on.isoformat(),
        "units": tuple(u.id for u in p.units),
        "inspections": tuple(b.inspection_id for b in p.bases),
    }


def _render_form(
    *,
    lang: str,
    country: str,
    current: rx.Prescription | None,
    values: Mapping[str, Any],
    failure: str | None,
) -> str:
    точки: tuple[rx.Choice, ...] = ()
    основания: tuple[rx.Choice, ...] = ()
    if country:
        точки, основания = rx.choices(country, reach=auth.current_reach())
    if current is not None:
        # Основание черновика старше последних проверок страны в выбор не
        # попадает — без этого сохранение молча сняло бы его с предписания.
        есть = {c.id for c in основания}
        основания = основания + tuple(
            rx.Choice(id=b.inspection_id, title=f"{b.unit_name} · {b.inspection_date}")
            for b in current.bases
            if b.known and b.inspection_id not in есть
        )
    return render_template(
        "actions/prescription_form.html",
        country=country,
        countries=country_data.countries(reach=auth.current_reach()),
        current=current,
        values=values,
        unit_choices=точки,
        base_choices=основания,
        bases_limit=rx.BASES_LIMIT,
        failure=failure,
        **_common(),
    )


def _render_list(conf: Settings) -> str:
    lang = _lang(conf)
    страна = country_data.normalize_code(request.args.get("country") or "")
    очередь = (request.args.get("queue") or "").strip()
    очередь = очередь if очередь in QUEUES else ""
    закрытые = request.args.get("closed") == "1"
    список = rx.list_prescriptions(reach=auth.current_reach(), closed=закрытые)
    сегодня = rx.today()
    все = список.rows
    страны = tuple(sorted({p.country for p in все}))
    в_стране = tuple(p for p in все if not страна or p.country == страна)
    очереди = {
        QUEUE_OVERDUE: tuple(p for p in в_стране if p.overdue(сегодня)),
        QUEUE_REPLIED: tuple(p for p in в_стране if p.status == rx.STATUS_ISSUED and p.replies),
        QUEUE_DRAFTS: tuple(p for p in в_стране if p.status == rx.STATUS_DRAFT),
    }

    def отбор(**изменения: str) -> str:
        параметры = {
            "country": страна,
            "queue": очередь,
            "closed": "1" if закрытые else "",
            "lang": lang,
            **изменения,
        }
        живые = {к: з for к, з in параметры.items() if з}
        return url_for("rx_list") + (f"?{urlencode(живые)}" if живые else "")

    return render_template(
        "actions/prescriptions.html",
        rows=очереди.get(очередь, в_стране),
        countries=страны,
        country=страна,
        queue=очередь,
        counts={к: len(з) for к, з in очереди.items()},
        closed=закрытые,
        truncated=список.truncated,
        limit=rx.LIST_LIMIT,
        select_url=отбор,
        **_common(),
    )


def _render_card(
    prescription_id: str, *, conf: Settings, notice: str | None, failure: str | None
) -> str | tuple[str, int]:
    lang = _lang(conf)
    предписание = rx.get_prescription(prescription_id, reach=auth.current_reach())
    if предписание is None:
        return _not_found()
    исход = request.args.get("gmail") or ""
    if notice is None and request.args.get("saved") == "1":
        notice = t("rx.saved", lang)
    return render_template(
        "actions/prescription.html",
        p=предписание,
        notice=notice,
        failure=failure,
        gmail=исход if исход in GMAIL_OUTCOMES else "",
        **_common(),
    )


# ── Раздел партнёра ────────────────────────────────────────────────────────


def _install_partner(app: Flask, conf: Settings, *, max_bytes: int) -> None:
    путь = section("orders").path

    @app.get(путь, endpoint="orders")
    def orders() -> Response | str:
        if is_hq():
            # У УК свой раздел (D264): здесь ему отвечать не на что.
            return redirect(url_for("rx_list", lang=_lang(conf)), code=303)
        закрытые = request.args.get("closed") == "1"
        список = rx.list_prescriptions(reach=auth.current_reach(), closed=закрытые)
        return render_template(
            "prescriptions/index.html",
            rows=список.rows,
            closed=закрытые,
            truncated=список.truncated,
            limit=rx.LIST_LIMIT,
            **_common(),
        )

    @app.get(f"{путь}/<prescription_id>", endpoint="order")
    def order(prescription_id: str) -> Response | str | tuple[str, int]:
        if is_hq():
            return redirect(
                url_for("rx_view", prescription_id=prescription_id, lang=_lang(conf)), code=303
            )
        return _render_partner_card(
            prescription_id, conf=conf, max_bytes=max_bytes, notice=None, failure=None
        )

    @app.post(f"{путь}/<prescription_id>/reply", endpoint="order_reply")
    def order_reply(prescription_id: str) -> str | tuple[str, int]:
        if is_hq():
            return render_template("users/forbidden.html"), 403
        refuse_foreign_origin()
        lang = _lang(conf)
        # Предел — только этому маршруту (D269), как у загрузки плана.
        request.max_content_length = max_bytes + FORM_OVERHEAD_BYTES
        мб = max_bytes // (1024 * 1024)

        def отказ(текст: str, код: int) -> tuple[str, int]:
            страница = _render_partner_card(
                prescription_id, conf=conf, max_bytes=max_bytes, notice=None, failure=текст
            )
            return (страница[0], код) if isinstance(страница, tuple) else (страница, код)

        try:
            файл = request.files.get("file")
            комментарий = request.form.get("comment") or ""
        except RequestEntityTooLarge:
            return отказ(t("rx.reply.too_big", lang, mb=мб), 413)
        вложение = None
        if файл is not None and файл.filename:
            вложение = rxw.Attachment(
                name=файл.filename,
                content_type=файл.mimetype or "",
                data=файл.read(max_bytes + 1),
            )
        try:
            rxw.reply(
                prescription_id,
                reach=auth.current_reach(),
                tenant=auth.current_tenant(),
                actor=_actor(),
                comment=комментарий,
                attachment=вложение,
                max_bytes=max_bytes,
            )
        except PrescriptionError as exc:
            return отказ(t("rx.failed", lang, reason=exc), 400)
        except StorageError as exc:
            # Текст хранилища называет корзину и ключ — партнёру он ни к чему.
            logger.warning("файл ответа на %s не лёг в хранилище: %s", prescription_id, exc)
            return отказ(t("rx.reply.storage_down", lang), 503)
        return _render_partner_card(
            prescription_id,
            conf=conf,
            max_bytes=max_bytes,
            notice=t("rx.reply.done", lang),
            failure=None,
        )

    @app.get(f"{путь}/files/<reply_id>", endpoint="order_file")
    def order_file(reply_id: str) -> FlaskResponse | tuple[str, int]:
        """Файл ответа — вложением, своей стране и УК. Чужой файл — тот же 404."""
        ссылка = rx.file_for_download(reply_id, reach=auth.current_reach())
        if ссылка is None:
            return "", 404
        try:
            байты = rx.fetch_file(ссылка)
        except (DbError, StorageError) as exc:
            logger.warning("файл ответа %s не выдан: %s", reply_id, exc)
            return "", 503
        # Любой формат отдаётся только вложением и без угадывания типа:
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


def _render_partner_card(
    prescription_id: str,
    *,
    conf: Settings,
    max_bytes: int,
    notice: str | None,
    failure: str | None,
) -> str | tuple[str, int]:
    предписание = rx.get_prescription(prescription_id, reach=auth.current_reach())
    if предписание is None:
        return _not_found()
    return render_template(
        "prescriptions/card.html",
        p=предписание,
        notice=notice,
        failure=failure,
        max_mb=max_bytes // (1024 * 1024),
        **_common(),
    )
