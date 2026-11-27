"""Факты для «Начала работы»: что есть у человека и в его пространстве (D756).

Читает базу и хранилище методик и отдаёт `onboarding.Facts` / `onboarding.SpaceFacts`;
решения здесь нет — оно в `onboarding.py`. Отказ чтения даёт `None` («не знаю»), а не
«нет»: напоминание по непрочитанному было бы ложью.

Состояние Claude и бота берётся из меню учётки (`account_menu.connections`), как у
`connect_reminder`: вторых источников нет.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import current_app

from src.bot import start_options
from src.db import queries, reach, spaces
from src.db.errors import DbError
from src.domain.permissions import role_may
from src.domain.tenants import canonical_tenant

from . import account_menu, auth, users_claude
from .onboarding import Facts, SpaceFacts
from .settings_screen import BOT_USERNAME_KEY

log = logging.getLogger(__name__)

#: Сколько живых учёток в пространстве значит «сотрудники заведены»: админ и ещё хоть один.
_PEOPLE_MIN = 2


def _read(what: str, fn: Any) -> Any:
    """Прочитать факт; отказ базы — `None` и строка в журнал."""
    try:
        return fn()
    except DbError as exc:
        log.warning("онбординг: %s не прочитано (%s)", what, exc.__class__.__name__)
        return None


def space_facts(tenant: str) -> SpaceFacts:
    """Страны, пиццерии и чек-лист пространства — для партнёра и для карточки у УК."""
    код = canonical_tenant(tenant or "")
    страны = _read("страны пространства", lambda: reach.countries_of(код))
    has_countries = None if страны is None else bool(страны)
    units: bool | None
    if страны is None:
        units = None
    elif not страны:
        units = False
    else:
        total = _read(
            "число пиццерий",
            lambda: queries.units_total(reach=reach.reach_of(код)),
        )
        units = None if total is None else total > 0
    checklists = start_options.open_checklists(код)
    return SpaceFacts(
        countries=has_countries,
        units=units,
        checklist=None if checklists is None else bool(checklists),
    )


def _connection_state(rows: list[account_menu.Connection], anchor: str) -> bool | None:
    state = next((row.state for row in rows if row.anchor == anchor), "unknown")
    return None if state == "unknown" else state == "on"


def person_facts(account: Any, *, tenant: str) -> Facts:
    """Что знает карточка о вошедшем: бот, Claude, люди, первая проверка и пространство."""
    код = canonical_tenant(tenant or "")
    rows = account_menu.connections(
        str(account.id),
        email=account.email,
        google_enabled=False,
        mcp_url=current_app.config.get(users_claude.MCP_URL_KEY),
    )
    people: bool | None = None
    if role_may(account.role, код, "people.manage"):
        overview = _read("люди пространства", spaces.overview)
        if overview is not None:
            mine = next((row for row in overview if row.code == код), None)
            people = mine is not None and mine.people >= _PEOPLE_MIN
    first = _first_inspection() if role_may(account.role, код, "inspection.conduct") else None
    return Facts(
        bot_bound=_connection_state(rows, "bot"),
        claude_connected=_connection_state(rows, "claude"),
        people_added=people,
        first_inspection=first,
        space=space_facts(код),
    )


def _first_inspection() -> bool | None:
    """Есть ли у пространства хоть одна проверка: принятая или ждущая вычитки."""
    охват = auth.current_reach()

    def has() -> bool:
        return bool(
            queries.list_inspections(reach=охват, limit=1)
            or queries.list_inspections(reach=охват, limit=1, on_review=True)
        )

    found: bool | None = _read("проверки пространства", has)
    return found


def bot_available() -> bool:
    """Настроен ли бот на площадке: без него шаг «привязать бота» не нужен."""
    return bool(current_app.config.get(BOT_USERNAME_KEY))
