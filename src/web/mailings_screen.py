"""Вкладка «Письма и уведомления» раздела «Администрирование» (D608, #1130, #977).

Один вопрос экрана: «кому уходит копия письма УК и каким текстом оно пишется». Слева
столбцом виды рассылки (письма по проверкам; предписания и экшн-планы встают следующими
этапами #1130) — у каждого видно, сколько адресов в копии; справа в панели выбранного вида
(`?kind=<код>`) его настройки. Каркас тот же, что у «Стран» (`docs/12-web-admin.md`,
«Каркас вкладки администрирования»).

**Только хранение.** Вкладка ничего не отправляет: адреса из списка подставляются в «Копию»
черновика, который человек сам кладёт в свою почту и сам отправляет (`letter_draft.py`,
`google_mail.create_draft`). Уведомлений, включаемых этой вкладкой, нет — нечему быть
включённым по умолчанию.

Видят и правят админ УК и главный админ (`mailing.manage`), остальным 404 на чтение и на
каждый POST. Список копий — `db/mailing_cc.py` (миграция `0103`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import Flask, abort, redirect, render_template, request
from flask import Response as FlaskResponse
from werkzeug.wrappers import Response

from src.db import mailing_cc
from src.db.errors import DbError, MailingCcError, MailingCcInputError

from . import administration, auth, guard, ui_lang
from .origin import refuse_foreign_origin
from .sections import section
from .users_view import TAB_MAILINGS

log = logging.getLogger(__name__)

#: Виды рассылки, которые вкладка уже ведёт, в порядке показа. Остальные виды из
#: `mailing_cc.KINDS` добавляются сюда этапами #1130 вместе со своим экраном.
SHOWN_KINDS: tuple[str, ...] = (mailing_cc.KIND_INSPECTION, mailing_cc.KIND_PLAN)

SAVED = "ok"
EXISTS = "exists"
INVALID = "invalid"
FAILED = "failed"
OUTCOMES = frozenset({SAVED, EXISTS, INVALID, FAILED})


@dataclass(frozen=True)
class KindLine:
    """Строка столбца: вид рассылки и сколько адресов в его копии (`None` — не прочиталось)."""

    kind: str
    cc_count: int | None


def _cc_counts() -> dict[str, int] | None:
    try:
        return mailing_cc.counts()
    except DbError:
        log.warning("Списки копий для вкладки «Письма» не прочитались", exc_info=True)
        return None


def _url(kind: str = "", saved: str = "") -> str:
    return administration.url(TAB_MAILINGS, kind=kind, saved=saved)


def show(conf_lang: str) -> FlaskResponse | tuple[str, int]:
    """Страница вкладки: столбец видов и, если выбран вид, его панель."""
    ui_lang.request_lang(conf_lang)
    counts = _cc_counts()
    lines = tuple(
        KindLine(kind, None if counts is None else counts.get(kind, 0)) for kind in SHOWN_KINDS
    )
    picked = request.args.get("kind", "").strip()
    if picked and picked not in SHOWN_KINDS:
        abort(404)
    emails: tuple[str, ...] | None = ()
    if picked:
        try:
            emails = mailing_cc.read(picked)
        except DbError:
            log.warning("Список копий вида %s не прочитался", picked, exc_info=True)
            emails = None
    saved = request.args.get("saved", "")
    return (
        render_template(
            "administration/mailings.html",
            lines=lines,
            picked=picked,
            emails=emails,
            outcome=saved if saved in OUTCOMES else "",
            partial_failed=counts is None,
            kind_url=lambda kind: _url(kind),
            cc_action=lambda action: (
                f"{request.script_root}{section('administration').path}"
                f"/mailings/{picked}/cc/{action}"
            ),
            split_open=bool(picked),
            split_back=_url(),
            **administration.nav(TAB_MAILINGS),
        ),
        200,
    )


def install(app: Flask) -> None:
    """Маршруты списка копий: добавить адрес и убрать (`mailing.manage`)."""
    base = section("administration").path + "/mailings/<kind>/cc"

    def _checked(kind: str) -> str:
        if kind not in SHOWN_KINDS:
            abort(404)
        return kind

    def _back(kind: str, outcome: str) -> Response:
        return redirect(_url(kind, outcome), code=303)

    def _actor() -> str:
        вошедший = auth.current_account()
        return вошедший.login if вошедший else ""

    @app.post(base + "/add", endpoint="mailing_cc_add")
    @guard.action("mailing.manage")
    def add(kind: str) -> Response:
        вид = _checked(kind)
        refuse_foreign_origin()
        try:
            new = mailing_cc.add(вид, request.form.get("email") or "", actor=_actor())
        except MailingCcInputError:
            # Кривой адрес человек чинит сам, сбой базы — нет: исходы разные.
            return _back(вид, INVALID)
        except MailingCcError:
            log.warning("Адрес копии вида %s не добавлен", вид, exc_info=True)
            return _back(вид, FAILED)
        return _back(вид, SAVED if new else EXISTS)

    @app.post(base + "/remove", endpoint="mailing_cc_remove")
    @guard.action("mailing.manage")
    def remove(kind: str) -> Response:
        вид = _checked(kind)
        refuse_foreign_origin()
        try:
            mailing_cc.remove(вид, request.form.get("email") or "")
        except MailingCcError:
            log.warning("Адрес копии вида %s не убран", вид, exc_info=True)
            return _back(вид, FAILED)
        return _back(вид, SAVED)
