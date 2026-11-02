"""Вкладка «Страны» раздела «Администрирование» (D640, D690).

Страны охвата — слева, выбранная карточка — в свободной области справа, без drawer;
без явного выбора открывается первая страна. На узком экране блоки идут друг за другом.
Партнёр — имена/почты контактов, отдельно от пространств доступа. Контакты и адресаты
проверок читаются из country_contacts; владение пространствами остаётся в «Пространствах».

Вкладка доступна по space.manage или contract.manage. Контакты, девелопера и языки
правит только space.manage; ОСБ ведёт договор. Страна вне охвата — 404. Контактные POST
объявлены в country_contacts_actions; прочие действия — в country_settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import abort, render_template, request

from src.db import country_contacts, country_contracts, country_report_langs
from src.db.errors import DbError
from src.db.reach import Reach
from src.domain.errors import ConfigError
from src.domain.permissions import role_may
from src.domain.tenants import HQ_TENANT

from . import (
    administration,
    auth,
    country_settings,
    country_summary,
    country_units,
    guard,
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


def _units(code: str, reach: Reach) -> UnitsData:
    try:
        return country_units.settings_rows(reach=reach, code=code)
    except DbError:
        log.warning("Country unit contacts could not be read")
        return UnitsData(profiles_failed=True)


def show(
    conf_lang: str,
    *,
    selected: str = "",
    contact_error: str = "",
    contact_draft: country_contacts.Fields | None = None,
    contact_ident: str = "",
) -> tuple[str, int]:
    """Страница вкладки: столбец стран и, если выбрана страна, её панель."""
    lang = ui_lang.request_lang(conf_lang)
    reach = auth.current_reach()
    known = country_data.countries(reach=reach)
    codes = tuple(code for code, _n in known)
    _by_dev, dev_of, dev_failed = country_summary.developers_of(codes)
    try:
        names = country_contacts.partner_names()
        owners, owners_failed = {c: ", ".join(v) for c, v in names.items()}, False
    except DbError:
        owners, owners_failed = {}, True
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
    raw = selected or request.args.get("country", "").strip()
    picked = country_data.normalize_code(raw) if raw else ""
    if raw and picked not in codes:
        abort(404)
    if not picked and lines:
        picked = lines[0].code
    panel = (
        country_settings.load(
            picked,
            dev_of.get(picked, ""),
            request.args.get("saved", ""),
            units=_units(picked, reach),
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
            contact_error=contact_error,
            contact_draft=contact_draft,
            contact_ident=contact_ident,
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
