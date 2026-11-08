"""Вкладка «Главная» раздела «Администрирование» (D728): настройки сети для главной.

Сейчас одна: показывать ли пиццерии «куда смотреть» в карточке «Требует внимания»
(критические нарушения и оценка D по проверкам периода). По умолчанию выключено —
функция понадобится позже. Задания доски в той же карточке настройка не трогает.

Видит и меняет тот, у кого есть `service.settings` (главный админ и админ УК), как и
переключатель экшн-планов. Значение лежит в `service_settings`; нечитаемое — выключено.
"""

from __future__ import annotations

import logging

from flask import Flask, Response, abort, g, make_response, redirect, render_template, request

from src.db import service_settings
from src.db.errors import DbError
from src.domain.features import home_attention_units_enabled
from src.domain.permissions import role_may
from src.settings_read import SettingsUnavailable, read_boolean

from . import administration, auth, guard, ui_lang
from .origin import refuse_foreign_origin
from .sections import section
from .users_view import TAB_HOME

log = logging.getLogger(__name__)

#: Действие матрицы, которое открывает вкладку и разрешает переключатель.
OPENING_ACTION = "service.settings"


def may_see(role: str | None, tenant: str | None) -> bool:
    return role_may(role, tenant, OPENING_ACTION)


def show(conf_lang: str, *, save_failed: bool = False) -> Response:
    if not guard.may(OPENING_ACTION):
        abort(404)
    ui_lang.request_lang(conf_lang)
    try:
        saved = read_boolean("home_attention_units")
        known = True
    except SettingsUnavailable:
        saved, known = None, False
    return make_response(
        render_template(
            "administration/home.html",
            attention_units=home_attention_units_enabled(),
            known=known,
            saved=saved,
            outcome=request.args.get("saved", ""),
            save_failed=save_failed,
            **administration.nav(TAB_HOME),
        )
    )


def install(app: Flask, conf_lang: str) -> None:
    @app.post(section("administration").path + "/home/settings", endpoint="home_setting")
    @guard.action(OPENING_ACTION)
    def save() -> Response:
        refuse_foreign_origin()
        value = request.form.get("attention_units")
        if value not in {"0", "1"}:
            abort(400)
        g.journal_target = f"home_attention_units={value}"
        account = auth.current_account()
        if account is None:
            abort(403)
        try:
            service_settings.set_home_attention_units(value == "1", actor=account.login)
        except DbError:
            log.warning("Home attention-units setting could not be saved")
            return make_response(show(conf_lang, save_failed=True), 503)
        return make_response(redirect(administration.url(TAB_HOME, saved="ok"), code=303))
