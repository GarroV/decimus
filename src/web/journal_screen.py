"""Экраны журналов (D462): «Журнал» главного админа и «Мои входы» человека.

Один вопрос — «что происходило с доступом»: кто входил и откуда, что менялось. Журнал
двух видов на одном экране двумя представлениями (`view=logins|actions`), период один
на экран (календарь «с — по», стрелки ← →, по умолчанию текущий месяц), человек — один
фильтр над таблицей.

* **«Журнал»** — вкладка экрана «Пользователи», только главному админу (прочим 404, как
  у «Подключений»): входы всех и действия админов, фильтр по человеку.
* **«Мои входы»** — `/settings/sign-ins`, любой роли: свои входы, фильтра по человеку нет.

**Кому чьи записи видны, решает база** (`0067`: функции чтения определяют зрителя по
токену его сессии), а не этот модуль: страница только просит. Фильтр `person` из адреса
права не расширяет — у обычного человека он ничего не меняет.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlencode

from flask import Flask, abort, render_template, request
from flask import Response as FlaskResponse

from src.db import journals
from src.db.errors import DbError

from . import access_policy, auth, registry_period, registry_view, ui_lang
from .config import Settings
from .db_refusal import note_target_mismatch
from .sections import section
from .texts import TEXTS, t
from .users_view import TAB_JOURNAL

_log = logging.getLogger(__name__)

VIEW_LOGINS = "logins"
VIEW_ACTIONS = "actions"
#: Строк за раз; схема отдаёт не больше тысячи.
LIMIT = journals.DEFAULT_LIMIT

OWN_PATH_SUFFIX = "sign-ins"


@dataclass(frozen=True)
class Filters:
    """Что выбрал человек: представление, кто и период."""

    view: str
    person: str | None
    period: registry_period.Period


def _uuid_or_none(raw: str | None) -> str | None:
    try:
        return str(uuid.UUID((raw or "").strip()))
    except ValueError:
        return None


def _bounds(period: registry_period.Period) -> tuple[datetime | None, datetime | None]:
    """Границы периода в UTC: начало включительно, конец — начало следующего дня."""
    начало = None if period.start is None else datetime.combine(period.start, time.min, UTC)
    конец = (
        None
        if period.end is None
        else datetime.combine(period.end + timedelta(days=1), time.min, UTC)
    )
    return начало, конец


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def action_label(code: str, lang: str) -> str:
    """Читаемая подпись кода действия; незнакомый код — как есть, журнал не падает."""
    ключ = f"journal.action.{code}"
    return t(ключ, lang) if ключ in TEXTS else code


def _filters(*, own: bool) -> Filters:
    view = VIEW_ACTIONS if request.args.get("view") == VIEW_ACTIONS and not own else VIEW_LOGINS
    person = None if own else _uuid_or_none(request.args.get("person"))
    return Filters(view, person, registry_period.read(request.args, today=date.today()))


def _login_rows(entries: tuple[journals.LoginEntry, ...]) -> list[dict[str, Any]]:
    return [
        {
            "time": _stamp(e.at),
            "login": e.login,
            "ip": e.ip,
            "browser": e.user_agent or "",
            "method": e.method,
            "result": e.result,
            "ok": e.result == "ok",
        }
        for e in entries
    ]


def _is_failed(outcome: str) -> bool:
    """Ответ — отказ или ошибка: код 4xx/5xx у веба, `failed` / `rejected` у MCP."""
    if outcome.isdigit():
        return int(outcome) >= 400
    return outcome in {"failed", "rejected"}


def _action_rows(entries: tuple[journals.ActionEntry, ...], lang: str) -> list[dict[str, Any]]:
    return [
        {
            "time": _stamp(e.at),
            "login": e.login,
            "role": e.role,
            "door": e.door,
            "ip": e.ip,
            "label": action_label(e.action, lang),
            "code": e.action,
            "target": e.target,
            "outcome": e.outcome,
            "failed": _is_failed(e.outcome),
        }
        for e in entries
    ]


def _render(*, own: bool, conf: Settings) -> FlaskResponse | tuple[str, int]:
    lang = ui_lang.request_lang(conf.ui_lang)
    filters = _filters(own=own)
    token = auth.current_session_token()
    начало, конец = _bounds(filters.period)
    failed = False
    rows: list[dict[str, Any]] = []
    people: tuple[tuple[str, str], ...] = ()
    try:
        if filters.view == VIEW_ACTIONS:
            rows = _action_rows(
                journals.read_actions(
                    token, person=filters.person, start=начало, end=конец, limit=LIMIT
                ),
                lang,
            )
        else:
            rows = _login_rows(
                journals.read_logins(
                    token, person=filters.person, start=начало, end=конец, limit=LIMIT
                )
            )
        if not own:
            people = journals.journal_people(token)
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("journal: журнал не прочитан (%s)", type(exc).__name__)
        failed = True

    base = (
        f"{request.script_root}{section('settings').path}/{OWN_PATH_SUFFIX}"
        if own
        else f"{request.script_root}{section('users').path}"
    )
    fixed = {} if own else {"tab": TAB_JOURNAL}

    def select(**изменения: str) -> str:
        параметры = {
            **fixed,
            "view": filters.view if not own else "",
            "person": filters.person or "",
            **filters.period.params(),
            "lang": lang,
            **изменения,
        }
        строка = urlencode({к: з for к, з in параметры.items() if з})
        return f"{base}?{строка}" if строка else base

    today = date.today()
    hidden = {
        к: з
        for к, з in {
            **fixed,
            "view": "" if own else filters.view,
            "person": filters.person or "",
            "lang": lang,
        }.items()
        if з
    }
    return (
        render_template(
            "journal/page.html",
            own=own,
            view=filters.view,
            person=filters.person or "",
            people=people,
            rows=rows,
            failed=failed,
            capped=len(rows) >= LIMIT,
            limit=LIMIT,
            period=filters.period,
            period_title=registry_view.period_title(filters.period, lang),
            period_prev=registry_view.period_link(filters.period, -1, select),
            period_next=registry_view.period_link(filters.period, 1, select),
            period_quick=registry_view.period_quick(filters.period, today, lang, select),
            period_hidden=hidden,
            period_action=base,
            view_url=lambda view: select(view=view),
            base=base,
            settings_url=f"{request.script_root}{section('settings').path}",
            # Табы «Пользователей»: журнал виден только главному админу, поэтому здесь все три.
            tab="journal",
            has_spaces_tab=not own,
            manages_spaces=True,
            has_connections_tab=not own,
            has_journal_tab=not own,
            link=lambda **параметры: (
                f"{request.script_root}{section('users').path}"
                + (f"?{urlencode(параметры)}" if параметры else "")
            ),
        ),
        503 if failed else 200,
    )


def _boss() -> None:
    """Только главный админ УК; для остальных 404 — снаружи экрана «Журнал» нет."""
    вошедший = auth.current_account()
    охват = None if вошедший is None else access_policy.scope_of(вошедший.role, вошедший.tenant)
    if вошедший is None or охват is None or охват.kind != access_policy.SUPER:
        abort(404)


def show_users(conf: Settings) -> FlaskResponse | tuple[str, int]:
    """GET `/users?tab=journal[&view=logins|actions][&person=<id>][&from=&to=]`."""
    _boss()
    return _render(own=False, conf=conf)


def install(app: Flask, conf: Settings) -> None:
    """«Мои входы»: чистое чтение, любой вошедший; чужие записи база не отдаст."""

    @app.get(f"{section('settings').path}/{OWN_PATH_SUFFIX}")
    def settings_signins() -> FlaskResponse | tuple[str, int]:
        return _render(own=True, conf=conf)
