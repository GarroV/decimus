"""Вкладка «Страны» раздела «Администрирование» (D640, D690).

Страны охвата — слева, выбранная карточка — в свободной области справа, без drawer;
без явного выбора открывается первая страна. На узком экране блоки идут друг за другом.
Партнёр — имена/почты контактов, отдельно от пространств доступа. Контакты и адресаты
проверок читаются из country_contacts; владение пространствами остаётся в «Пространствах».

Вкладка доступна по space.manage; он же правит контакты, девелопера и языки. Страна вне
охвата — 404. Контактные POST объявлены в country_contacts_actions; прочие действия — в
country_settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from flask import abort, render_template, request

from src.db import country_contacts
from src.db.errors import DbError
from src.db.reach import Reach
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

#: Действие матрицы, которое открывает вкладку.
OPENING_ACTIONS = ("space.manage",)


def may_see(role: str | None, tenant: str | None) -> bool:
    """Может ли эта роль в этом пространстве открыть вкладку «Страны»."""
    return any(role_may(role, tenant, action) for action in OPENING_ACTIONS)


@dataclass(frozen=True)
class CountryLine:
    """Строка столбца: код и название страны; всё остальное — в панели справа."""

    code: str
    name: str


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
    _by_dev, dev_of, _dev_failed = country_summary.developers_of(codes)
    lines = tuple(
        CountryLine(code, country_title(code, lang))
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
            country_url=lambda code: administration.url(TAB_COUNTRIES, country=code),
            split_open=bool(picked),
            split_back=administration.url(TAB_COUNTRIES),
            **administration.nav(TAB_COUNTRIES),
        ),
        200,
    )
