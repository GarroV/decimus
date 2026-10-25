"""Вкладка «Страны» раздела «Администрирование» (D640, #1251).

Слева столбцом страны охвата вошедшего — у каждой партнёр (пространство) и девелопер,
справа в панели настройки выбранной (`?tab=countries&country=<код>`): девелопер, партнёр,
языки отчёта и договор. Панель — та же, что карточка на экране страны
(`country_settings.load`, `country/_settings.html`), только с формами правки: на экране
страны она остаётся чтением со ссылкой сюда.

Вкладка открыта тем, у кого в матрице есть `space.manage` или `contract.manage` (главный,
админ УК, ОСБ) — права не менялись. Что именно можно править, решают те же коды: ОСБ видит
договор и не видит форм девелопера, партнёра и языков. Страна вне охвата или без пиццерий в
справочнике — 404, как у несуществующей. Маршруты действий — `country_settings.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import Response as FlaskResponse
from flask import abort, render_template, request

from src.db.errors import DbError
from src.domain.permissions import role_may
from src.domain.tenants import HQ_TENANT

from . import (
    administration,
    auth,
    country_settings,
    country_summary,
    guard,
    partner_spaces,
    ui_lang,
)
from . import country as country_data
from .country_units import UnitsData
from .geo_names import country_title
from .users_view import TAB_COUNTRIES

log = logging.getLogger(__name__)

#: Действия матрицы, любое из которых открывает вкладку.
OPENING_ACTIONS = ("space.manage", "contract.manage")


def may_see(role: str | None, tenant: str | None) -> bool:
    """Может ли эта роль в этом пространстве открыть вкладку «Страны»."""
    return any(role_may(role, tenant, action) for action in OPENING_ACTIONS)


@dataclass(frozen=True)
class CountryLine:
    """Строка столбца: код, название, пространство-партнёр и девелопер (пусто — не задан)."""

    code: str
    name: str
    space: str
    developer: str


def _owners() -> tuple[dict[str, str], bool]:
    """`{код страны: название пространства}`; не прочиталось — пусто и отметка."""
    try:
        spaces = partner_spaces.overview()
    except DbError:
        log.warning("Пространства партнёров для вкладки «Страны» не прочитались", exc_info=True)
        return {}, True
    return {c: (s.name or s.code) for s in spaces for c in s.countries}, False


def show(conf_lang: str) -> FlaskResponse | tuple[str, int]:
    """Страница вкладки: столбец стран и, если выбрана страна, её панель."""
    lang = ui_lang.request_lang(conf_lang)
    reach = auth.current_reach()
    known = country_data.countries(reach=reach)
    codes = tuple(code for code, _n in known)
    _by_dev, dev_of, dev_failed = country_summary.developers_of(codes)
    owners, owners_failed = _owners()
    lines = tuple(
        CountryLine(code, country_title(code, lang), owners.get(code, ""), dev_of.get(code, ""))
        for code in sorted(codes, key=lambda c: country_title(c, lang).casefold())
    )
    raw = request.args.get("country", "").strip()
    picked = country_data.normalize_code(raw) if raw else ""
    if raw and picked not in codes:
        abort(404)
    panel = (
        country_settings.load(
            picked,
            dev_of.get(picked, ""),
            request.args.get("saved", ""),
            units=UnitsData(),
            can_edit=guard.may("space.manage"),
            show_email=auth.current_tenant() == HQ_TENANT,
            can_contract=guard.may("contract.manage"),
            settings_only=True,
        )
        if picked
        else None
    )
    return (
        render_template(
            "administration/countries.html",
            lines=lines,
            picked=picked,
            panel=panel,
            partial_failed=dev_failed or owners_failed,
            country_url=lambda code: administration.url(TAB_COUNTRIES, country=code),
            split_open=bool(picked),
            split_back=administration.url(TAB_COUNTRIES),
            **administration.nav(TAB_COUNTRIES),
        ),
        200,
    )
