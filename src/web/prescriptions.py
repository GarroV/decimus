"""Предписания в вебе: вкладка «Предписания» «Действий» и записи (D266, D270, D275, D526, D599).

Раздел «Действия» один у УК и партнёра (D526): список и панель выбранного
предписания — экран `actions_screen`, здесь данные вкладки и записи. Ведёт
предписания УК на странице «ОСБ» (`osb.py`); у «Действий» у тех, кому эта
страница открыта, вкладка «Предписания» переходит на неё.

Сотрудник УК с правом `prescription.request` (девелопер, админ, ОСБ, главный
админ) составляет предписание на отдельной странице формы — письмо длинное — и
отправляет его на согласование. Согласует, возвращает с комментарием, кладёт
письмо черновиком в свою почту Gmail и закрывает только ведущий —
`prescription.manage` (ОСБ, главный админ): каждый такой маршрут объявляет это
кодом, а не ролью. Партнёр: свои страны по охвату (D284), ответ комментарием и
файлом. Файл ответа скачивают своя страна и УК; чужой отвечает тем же 404.

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

from flask import Flask, abort, current_app, redirect, render_template, request, send_file, url_for
from flask import Response as FlaskResponse
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import country_contracts as contracts_db
from src.db import prescriptions as rx
from src.db import prescriptions_write as rxw
from src.db.config import load_action_plan_settings
from src.db.errors import (
    DbError,
    IssuedDraftLostError,
    PrescriptionError,
    StorageConfigError,
    StorageError,
)
from src.domain.errors import ConfigError

from . import actions_columns as columns
from . import actions_screen, auth, guard, ui_lang
from . import country as country_data
from .action_plans import FORM_OVERHEAD_BYTES, is_hq
from .actions_screen import TAB_RX
from .config import Settings
from .geo_names import country_title
from .google_mail import GoogleMailError, MailAccountMismatchError, create_draft
from .letter_draft import MAIL_CONSENT_KEY, MAIL_RETURNS_KEY, OUTCOME_WRONG_ACCOUNT, MailReturn
from .letter_markup import from_plain
from .origin import refuse_foreign_origin
from .sections import section
from .texts import t

logger = logging.getLogger(__name__)

#: Вид похода за почтовым согласием (кука `letter_draft`).
MAIL_KIND = "prescription"

#: Чем кончается форма (поле `then`): сохранить черновик; сохранить и отправить на
#: согласование (девелопер, админ); сохранить и согласовать (ОСБ, главный админ).
THEN_SAVE = "save"
THEN_REQUEST = "request"
THEN_APPROVE = "approve"
#: Что пришло в адрес панели после сохранения формы (`?saved=`) — какое сообщение показать.
SAVED_DRAFT = "1"
SAVED_REQUESTED = "requested"
SAVED_APPROVED = "approved"

#: Исходы похода в Gmail, которые экран умеет назвать словами.
GMAIL_OUTCOMES = ("ok", "failed", "denied", "unavailable", "lost", OUTCOME_WRONG_ACCOUNT)

#: Тон метки состояния — классы `tag` из `forma`.
STATE_TONES = {
    rx.STATE_DRAFT: "tag--neutral",
    rx.STATE_REVIEW: "tag--warn",
    rx.STATE_APPROVED: "tag--violet",
    rx.STATE_ACTIVE: "tag--accent",
    rx.STATE_OVERDUE: "tag--err",
    rx.STATE_CLOSED: "tag--ok",
}

EMPTY = rx.PrescriptionList(rows=(), truncated=False)


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


def _require_hq() -> None:
    """Второй заслон раздела УК — на самом маршруте (первый — `before_request`)."""
    if not is_hq():
        abort(404)


def not_found() -> tuple[str, int]:
    """Чужое, черновое для партнёра и несуществующее — один ответ, но про предписание."""
    назад = url_for("osb") if guard.may("view.osb") else url_for("actions", tab=TAB_RX)
    return render_template("prescriptions/not_found.html", back=назад), 404


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip()[:10])
    except ValueError:
        return None


def _base() -> str:
    """Адрес предписаний: форма составления, действия УК и ответ партнёра лежат под ним."""
    return section("actions").path + "/prescriptions"


def _files_path() -> str:
    return section("actions").path + "/prescription-files"


def common() -> dict[str, Any]:
    """Общее для экрана «Действий» и страницы «ОСБ»: сегодня, тона, адреса."""
    return {
        "today": rx.today(),
        "rx_tones": STATE_TONES,
        "rx_base": _base(),
        "rx_files_path": _files_path(),
        "actions_path": section("actions").path,
        "registry_path": section("registry").path,
    }


def screen_tab() -> str:
    """Какой экран отвечает на действие: «ОСБ» — тем, кому она открыта, иначе «Действия»."""
    return actions_screen.TAB_OSB if guard.may("view.osb") else TAB_RX


def panel_url(ident: str, lang: str, **extra: str) -> str:
    """Адрес экрана с открытой панелью предписания — куда возвращаются после действия."""
    return actions_screen.panel_link(screen_tab(), ident, lang=lang, **extra)


def acts_for(p: rx.Prescription | None) -> dict[str, bool]:
    """Что вошедший может сделать с предписанием в панели — по статусу, праву и авторству.

    Право решает матрица (`prescription.request`, `prescription.manage`), статус —
    жизненный цикл (0087). Автор правит свой черновик и отправляет его на
    согласование; ОСБ и главный админ правят всё неотправленное, согласуют,
    возвращают, кладут письмо в почту и закрывают. Свой черновик ведущий согласует
    сразу; чужой — после того, как автор запросил. Админ без `manage` кнопок не видит.
    """
    none = {"edit": False, "request": False, "approve": False, "return": False}
    none |= {"send": False, "close": False}
    if p is None or not is_hq():
        return none
    ведущий = guard.may("prescription.manage")
    автор = guard.may("prescription.request") and p.created_by == _actor()
    черновик = p.status == rx.STATUS_DRAFT
    return {
        "edit": p.status in rx.UNSENT and (ведущий or (черновик and автор)),
        "request": черновик and автор and not ведущий,
        "approve": ведущий
        and (p.status == rx.STATUS_REVIEW or (черновик and p.created_by == _actor())),
        "return": ведущий and p.status == rx.STATUS_REVIEW,
        "send": ведущий and p.status == rx.STATUS_APPROVED,
        "close": ведущий and p.status == rx.STATUS_ISSUED,
    }


def returned_note(p: rx.Prescription | None) -> str | None:
    """Комментарий последнего возврата — автору, пока черновик не ушёл на согласование снова."""
    if p is None or p.status != rx.STATUS_DRAFT:
        return None
    возвраты = [e for e in p.events if e.action == "returned"]
    return (возвраты[-1].detail or None) if возвраты else None


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
    }


def install(app: Flask, conf: Settings) -> None:
    """Повесить маршруты вкладки и возврат из похода в Gmail."""
    max_bytes = load_action_plan_settings().max_bytes
    actions_screen.register(
        app,
        TAB_RX,
        actions_screen.Tab(
            screen=lambda lang: screen_context(lang),
            panel=lambda item_id, **outcome: panel_context(item_id, max_bytes=max_bytes, **outcome),
            missing=not_found,
        ),
    )
    _install_hq(app, conf)
    _install_partner(app, conf, max_bytes=max_bytes)
    _install_legacy(app)
    app.extensions.setdefault(MAIL_RETURNS_KEY, {})[MAIL_KIND] = MailReturn(
        back=_back_from_gmail, finish=_finish_gmail
    )


# ── Данные вкладки ──────────────────────────────────────────────────────────


def screen_context(lang: str) -> dict[str, Any]:
    """Список предписаний — столбец стран и блоки, как у «ОСБ»; охват решает объём (D526, D611)."""
    страна = country_data.normalize_code(request.args.get("country") or "")
    новый_адрес: dict[str, Any] = {k: v for k, v in (("country", страна), ("lang", lang)) if v}
    return {
        **columns.rx_screen(
            lang,
            endpoint="actions",
            fixed={"tab": TAB_RX},
            count_closed=False,
            empty_key="rx.list.empty" if is_hq() else "rx.partner.empty",
            title_key="section.actions.title",
        ),
        "hq": is_hq(),
        "new_url": url_for("rx_new", **новый_адрес),
        **common(),
    }


def panel_context(
    prescription_id: str,
    *,
    max_bytes: int,
    notice: str | None = None,
    failure: str | None = None,
    gmail: str = "",
) -> dict[str, Any]:
    """Панель предписания: само предписание в охвате вошедшего и то, что на нём можно делать."""
    предписание = None
    не_прочитано = False
    try:
        предписание = rx.get_prescription(prescription_id, reach=auth.current_reach())
    except DbError as exc:
        logger.warning("предписание %s не прочитано: %s", prescription_id, exc)
        не_прочитано = True
    return {
        "item": предписание,
        "failed": не_прочитано,
        "notice": notice,
        "failure": failure,
        "gmail": gmail if gmail in GMAIL_OUTCOMES else "",
        "hq": is_hq(),
        "acts": acts_for(предписание),
        "returned_note": returned_note(предписание),
        "max_mb": max_bytes // (1024 * 1024),
        **common(),
    }


def _respond(
    conf: Settings,
    prescription_id: str,
    *,
    notice: str | None = None,
    failure: str | None = None,
    status: int = 200,
) -> str | tuple[str, int]:
    return actions_screen.respond(
        conf, screen_tab(), item_id=prescription_id, notice=notice, failure=failure, status=status
    )


# ── Запись УК ───────────────────────────────────────────────────────────────


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
    путь = _base()

    @app.get(f"{путь}/new", endpoint="rx_new")
    def rx_new() -> str:
        _require_hq()
        lang = _lang(conf)
        страна = country_data.normalize_code(request.args.get("country") or "")
        # «Сформировать предписание» с карточки проверки (решение владельца 11.10.2026): проверка
        # уже выбрана основанием, страна берётся с её точки. Проверка вне охвата, чужая или
        # не принятая — форма открывается пустой, без молчаливого чужого основания.
        основание = _basis_from_card()
        значения = _defaults(страна, lang)
        if основание is not None:
            страна = основание[0]
            значения = {**_defaults(страна, lang), "inspections": (основание[1].id,)}
        return _render_form(
            lang=lang,
            country=страна,
            current=None,
            values=значения,
            failure=None,
            extra_bases=(основание[1],) if основание is not None else (),
        )

    @app.post(путь, endpoint="rx_create")
    @guard.action("prescription.request")
    def rx_create() -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        страна = country_data.normalize_code(request.form.get("country") or "")
        then = request.form.get("then") or THEN_SAVE
        ведущий = guard.may("prescription.manage")
        if then == THEN_APPROVE and not ведущий:
            return guard.forbidden()
        try:
            черновик = _draft_from_form(страна)
            if not ведущий and not черновик.inspection_ids:
                # Предписание без проверки-основания заводит только ОСБ (D599).
                raise PrescriptionError(t("rx.need_base", lang))
            ident = rxw.create_draft(черновик, actor=_actor(), submit=then == THEN_REQUEST)
        except PrescriptionError as exc:
            return _render_form(
                lang=lang,
                country=страна,
                current=None,
                values=_form_values(),
                failure=t("rx.failed", lang, reason=exc),
            ), 400
        return _after_save(conf, ident, lang, then=then)

    @app.get(f"{путь}/<prescription_id>/edit", endpoint="rx_edit")
    def rx_edit(prescription_id: str) -> Response | str | tuple[str, int]:
        _require_hq()
        lang = _lang(conf)
        текущее = rx.get_prescription(prescription_id, reach=auth.current_reach())
        if текущее is None:
            return not_found()
        if not acts_for(текущее)["edit"]:
            return redirect(panel_url(текущее.id, lang), code=303)
        return _render_form(
            lang=lang,
            country=текущее.country,
            current=текущее,
            values=_values_of(текущее),
            failure=None,
        )

    @app.post(f"{путь}/<prescription_id>/edit", endpoint="rx_update")
    @guard.action("prescription.request")
    def rx_update(prescription_id: str) -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        текущее = rx.get_prescription(prescription_id, reach=auth.current_reach())
        if текущее is None:
            return not_found()
        then = request.form.get("then") or THEN_SAVE
        ведущий = guard.may("prescription.manage")
        if then == THEN_APPROVE and not ведущий:
            return guard.forbidden()
        try:
            черновик = _draft_from_form(текущее.country)
            if not ведущий and not черновик.inspection_ids:
                # Как в rx_create: снять все основания и оставить предписание без
                # проверки может только ОСБ (D599).
                raise PrescriptionError(t("rx.need_base", lang))
            rxw.update_draft(
                текущее.id,
                черновик,
                actor=_actor(),
                manager=ведущий,
                submit=then == THEN_REQUEST,
            )
        except PrescriptionError as exc:
            return _render_form(
                lang=lang,
                country=текущее.country,
                current=текущее,
                values=_form_values(),
                failure=t("rx.failed", lang, reason=exc),
            ), 400
        return _after_save(conf, текущее.id, lang, then=then)

    @app.post(f"{путь}/<prescription_id>/request", endpoint="rx_request")
    @guard.action("prescription.request")
    def rx_request(prescription_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        try:
            rxw.request_review(
                prescription_id, actor=_actor(), manager=guard.may("prescription.manage")
            )
        except PrescriptionError as exc:
            return _respond(conf, prescription_id, failure=t("rx.failed", lang, reason=exc))
        return _respond(conf, prescription_id, notice=t("rx.requested", lang))

    @app.post(f"{путь}/<prescription_id>/approve", endpoint="rx_approve")
    @guard.action("prescription.manage")
    def rx_approve(prescription_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        try:
            rxw.approve(prescription_id, actor=_actor())
        except PrescriptionError as exc:
            return _respond(conf, prescription_id, failure=t("rx.failed", lang, reason=exc))
        return _respond(conf, prescription_id, notice=t("rx.approved", lang))

    @app.post(f"{путь}/<prescription_id>/return", endpoint="rx_return")
    @guard.action("prescription.manage")
    def rx_return(prescription_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        try:
            rxw.return_to_author(
                prescription_id, actor=_actor(), comment=request.form.get("comment") or ""
            )
        except PrescriptionError as exc:
            return _respond(conf, prescription_id, failure=t("rx.failed", lang, reason=exc))
        return _respond(conf, prescription_id, notice=t("rx.returned", lang))

    @app.post(f"{путь}/<prescription_id>/send", endpoint="rx_send")
    @guard.action("prescription.manage")
    def rx_send(prescription_id: str) -> Response | str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        текущее = rx.get_prescription(prescription_id, reach=auth.current_reach())
        if текущее is None:
            return not_found()
        if текущее.status != rx.STATUS_APPROVED:
            # В Google ходить незачем: без согласования письмо не уходит (D600).
            причина = t("rx.not_approved", lang)
            return _respond(conf, текущее.id, failure=t("rx.failed", lang, reason=причина))
        return _go_to_gmail(текущее.id, lang)

    @app.post(f"{путь}/<prescription_id>/close", endpoint="rx_close")
    @guard.action("prescription.manage")
    def rx_close(prescription_id: str) -> str | tuple[str, int]:
        _require_hq()
        refuse_foreign_origin()
        lang = _lang(conf)
        try:
            rxw.close(prescription_id, actor=_actor(), comment=request.form.get("comment") or "")
        except PrescriptionError as exc:
            return _respond(conf, prescription_id, failure=t("rx.failed", lang, reason=exc))
        return _respond(conf, prescription_id, notice=t("rx.closed", lang))


def _after_save(
    conf: Settings, ident: str, lang: str, *, then: str
) -> Response | str | tuple[str, int]:
    """После сохранения формы: на панель; «согласовать» — сразу следующим шагом (ведущий)."""
    if then == THEN_APPROVE:
        try:
            rxw.approve(ident, actor=_actor())
        except PrescriptionError as exc:
            # Черновик уже сохранён — говорим, почему не согласовался, и показываем его.
            return _respond(conf, ident, failure=t("rx.failed", lang, reason=exc))
        return redirect(panel_url(ident, lang, saved=SAVED_APPROVED), code=303)
    saved = SAVED_REQUESTED if then == THEN_REQUEST else SAVED_DRAFT
    return redirect(panel_url(ident, lang, saved=saved), code=303)


def _go_to_gmail(ident: str, lang: str) -> Response:
    начать: Callable[[str, str, str], Response | None] = current_app.extensions[MAIL_CONSENT_KEY]
    поход = начать(MAIL_KIND, ident, lang)
    if поход is None:
        # Законная настройка стенда: без реквизитов Google черновика нет, и
        # предписание остаётся согласованным — экран говорит это словами.
        return _back_from_gmail(ident, lang, "unavailable")
    return поход


def _back_from_gmail(ident: str, lang: str, outcome: str) -> Response:
    return redirect(panel_url(ident, lang, gmail=outcome), code=303)


def _finish_gmail(ident: str, lang: str, token: Callable[[], str]) -> Response:
    """Возврат от Google: положить черновик и в той же транзакции отметить «действует»."""
    if not is_hq() or not guard.may("prescription.manage"):
        # Возврат — общий адрес `/auth/google/mail`, раздел УК его не прикрывает;
        # письмо предписания кладёт только ведущий (ОСБ, главный админ).
        abort(404)
    try:
        доступ = token()
    except MailAccountMismatchError as exc:
        # Чужой аккаунт Google (D176): черновика нет, предписание не отмечается.
        logger.warning("предписание %s: %s", ident, exc)
        return _back_from_gmail(ident, lang, OUTCOME_WRONG_ACCOUNT)
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


def _default_recipients(country: str) -> str:
    """«Кому» пустой формы: контакты по ДКК страны (D603); нет их — запомненные (D275)."""
    try:
        контакты = contracts_db.dkk_recipients(country)
    except (DbError, ConfigError) as exc:
        logger.warning("контакты по ДКК страны %s не прочитаны: %s", country, exc)
        контакты = ""
    if контакты:
        return контакты
    try:
        return rx.remembered_recipients(country)
    except PrescriptionError as exc:
        logger.warning("адреса страны %s не прочитаны: %s", country, exc)
        return ""


def _defaults(country: str, lang: str) -> dict[str, Any]:
    """Пустая форма: адресаты страны (ДКК, иначе запомненные), тема по стране."""
    адресаты = _default_recipients(country) if country else ""
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


def _basis_from_card() -> tuple[str, rx.Choice] | None:
    ident = (request.args.get("inspection") or "").strip()
    if not ident:
        return None
    try:
        return rx.inspection_basis(ident, reach=auth.current_reach())
    except PrescriptionError as exc:
        logger.warning("основание предписания %s не прочитано: %s", ident, exc)
        return None


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
    extra_bases: tuple[rx.Choice, ...] = (),
) -> str:
    ведущий = guard.may("prescription.manage")
    точки: tuple[rx.Choice, ...] = ()
    основания: tuple[rx.Choice, ...] = ()
    if country:
        точки, основания = rx.choices(country, reach=auth.current_reach())
    # Основание с карточки старше последних проверок страны в выбор не попадает —
    # без этой строки его нечем было бы отметить.
    есть_с_карточки = {c.id for c in основания}
    основания = основания + tuple(c for c in extra_bases if c.id not in есть_с_карточки)
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
        is_manager=ведущий,
        can_request=not ведущий and (current is None or current.status == rx.STATUS_DRAFT),
        can_approve=ведущий and (current is None or acts_for(current)["approve"]),
        back_url=(
            panel_url(current.id, lang)
            if current is not None
            else (
                url_for("osb", lang=lang)
                if guard.may("view.osb")
                else url_for("actions", tab=TAB_RX, lang=lang)
            )
        ),
        bases_limit=rx.BASES_LIMIT,
        failure=failure,
        **common(),
    )


# ── Запись партнёра и файлы ─────────────────────────────────────────────────


def _install_partner(app: Flask, conf: Settings, *, max_bytes: int) -> None:
    путь = _base()

    @app.post(f"{путь}/<prescription_id>/reply", endpoint="order_reply")
    @guard.action("prescription.reply")
    def order_reply(prescription_id: str) -> str | tuple[str, int]:
        if is_hq():
            return render_template("users/forbidden.html"), 403
        refuse_foreign_origin()
        lang = _lang(conf)
        # Предел — только этому маршруту (D269), как у загрузки плана.
        request.max_content_length = max_bytes + FORM_OVERHEAD_BYTES
        мб = max_bytes // (1024 * 1024)

        def отказ(текст: str, код: int) -> str | tuple[str, int]:
            return _respond(conf, prescription_id, failure=текст, status=код)

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
        except StorageConfigError as exc:
            logger.error("файл ответа на %s: хранилище не настроено: %s", prescription_id, exc)
            return отказ(t("files.storage_unset", lang), 503)
        except StorageError as exc:
            # Текст хранилища называет корзину и ключ — партнёру он ни к чему.
            logger.warning("файл ответа на %s не лёг в хранилище: %s", prescription_id, exc)
            return отказ(t("rx.reply.storage_down", lang), 503)
        return _respond(conf, prescription_id, notice=t("rx.reply.done", lang))

    @app.get(f"{section('actions').path}/prescription-files/<reply_id>", endpoint="order_file")
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


# ── Старые адреса ───────────────────────────────────────────────────────────


def _install_legacy(app: Flask) -> None:
    """Адреса до D526 переадресуют в «Действия»: закладки и ссылки не ломаются."""
    путь = _base()

    @app.get(путь, endpoint="rx_list")
    def rx_list() -> Response:
        return actions_screen.redirect_to_screen(TAB_RX)

    @app.get(f"{путь}/<prescription_id>", endpoint="rx_view")
    def rx_view(prescription_id: str) -> Response:
        return actions_screen.redirect_to_screen(TAB_RX, prescription_id)

    @app.get("/prescriptions", endpoint="orders")
    def orders() -> Response:
        return actions_screen.redirect_to_screen(TAB_RX)

    @app.get("/prescriptions/<prescription_id>", endpoint="order")
    def order(prescription_id: str) -> Response:
        return actions_screen.redirect_to_screen(TAB_RX, prescription_id)

    @app.get("/prescriptions/files/<reply_id>", endpoint="order_file_legacy")
    def order_file_legacy(reply_id: str) -> Response:
        return redirect(url_for("order_file", reply_id=reply_id), code=303)
