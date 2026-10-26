"""Вкладка «Страны» раздела «Администрирование» (D640, #1251).

Слева столбцом страны охвата вошедшего — у каждой что настроено: партнёр (пространство),
девелопер, языки отчёта и, у кого есть `contract.manage`, договор («есть» / «нет»); языки и
договоры дочитываются по одному запросу на все страны, а не по запросу на страну. Справа
в панели настройки выбранной (`?tab=countries&country=<код>`): четыре блока — партнёр,
девелопер, языки отчёта и договор. Панель — макрос карточки страны (`country_settings.load`,
`country/_settings.html`, режим `settings_only`): на экране страны та же карточка остаётся
чтением со ссылкой сюда.

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

from src.db import country_contracts, country_report_langs
from src.db.errors import DbError
from src.domain.errors import ConfigError
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
    """Строка столбца: код, название, что настроено у страны.

    Партнёр (пространство) и девелопер — пусто, если не заданы. `langs` — языки, заданные
    для страны (пусто — «по умолчанию»), `None` — не прочитались. `has_contract` — есть ли
    строка договора, `None` — не прочиталось.
    """

    code: str
    name: str
    space: str
    developer: str
    langs: tuple[str, ...] | None = ()
    has_contract: bool | None = False


def _owners() -> tuple[dict[str, str], bool]:
    """`{код страны: название пространства}`; не прочиталось — пусто и отметка."""
    try:
        spaces = partner_spaces.overview()
    except DbError:
        log.warning("Пространства партнёров для вкладки «Страны» не прочитались", exc_info=True)
        return {}, True
    return {c: (s.name or s.code) for s in spaces for c in s.countries}, False


def _langs_by_country() -> dict[str, tuple[str, ...]] | None:
    """Языки отчёта, заданные для стран, одним запросом; не прочиталось — `None`."""
    try:
        return country_report_langs.read_all()
    except DbError:
        log.warning("Языки отчёта стран для вкладки «Страны» не прочитались", exc_info=True)
        return None


def _contract_countries() -> frozenset[str] | None:
    """Страны с заполненным договором одним запросом; не прочиталось — `None`."""
    try:
        return country_contracts.countries_with_contract()
    except (DbError, ConfigError):
        log.warning("Договоры стран для вкладки «Страны» не прочитались", exc_info=True)
        return None


def show(conf_lang: str) -> FlaskResponse | tuple[str, int]:
    """Страница вкладки: столбец стран и, если выбрана страна, её панель."""
    lang = ui_lang.request_lang(conf_lang)
    reach = auth.current_reach()
    known = country_data.countries(reach=reach)
    codes = tuple(code for code, _n in known)
    _by_dev, dev_of, dev_failed = country_summary.developers_of(codes)
    owners, owners_failed = _owners()
    show_contract = auth.current_tenant() == HQ_TENANT and guard.may("contract.manage")
    langs = _langs_by_country()
    with_contract = _contract_countries() if show_contract else frozenset()
    lines = tuple(
        CountryLine(
            code,
            country_title(code, lang),
            owners.get(code, ""),
            dev_of.get(code, ""),
            None if langs is None else langs.get(code, ()),
            None if with_contract is None else code in with_contract,
        )
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
            partial_failed=dev_failed
            or owners_failed
            or langs is None
            or (show_contract and with_contract is None),
            show_contract=show_contract,
            country_url=lambda code: administration.url(TAB_COUNTRIES, country=code),
            split_open=bool(picked),
            split_back=administration.url(TAB_COUNTRIES),
            **administration.nav(TAB_COUNTRIES),
        ),
        200,
    )
