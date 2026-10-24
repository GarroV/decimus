"""Экран «Расход модели» (D537): сколько токенов и денег ушло на модель.

Вкладка экрана «Пользователи» (`/users?tab=usage`), как «Журнал»: один вопрос — «сколько
мы тратим на модель и на что». Период один на экран (календарь «с — по», стрелки ← →,
по умолчанию текущий месяц). Сверху итоги с изменением к прошлому периоду, ниже срезы:
по дням, по видам вызова, по людям, самые дорогие проверки.

**Видят главный админ и админ УК** (`access_policy`: охват `SUPER` и `HQ_ADMIN`); прочим
404 — снаружи экрана нет. Заслон дублирует база: `model_usage_read` отдаёт пустое всем,
кроме этих двух ролей, поэтому ошибка здесь не откроет чужого расхода. Деньги — оценка
по `recognize/model_prices.json`, подпись «оценка» стоит у каждой суммы.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlencode

from flask import Response as FlaskResponse
from flask import abort, render_template, request

from src.db import model_usage
from src.db.errors import DbError
from src.domain.model_usage import KINDS

from . import access_policy, auth, registry_period, registry_view, ui_lang, usage_view
from .config import Settings
from .db_refusal import note_target_mismatch
from .sections import section
from .texts import TEXTS, t
from .users_view import TAB_USAGE

_log = logging.getLogger(__name__)

#: Кто видит расход: охваты главного админа и админа УК.
VIEWER_KINDS = frozenset({access_policy.SUPER, access_policy.HQ_ADMIN})


def may_see(role: str | None, tenant: str | None) -> bool:
    """Может ли эта роль в этом пространстве открыть расход модели."""
    охват = access_policy.scope_of(role, tenant)
    return охват is not None and охват.kind in VIEWER_KINDS


def _bounds(period: registry_period.Period) -> tuple[datetime | None, datetime | None]:
    """Границы периода в UTC: начало включительно, конец — начало следующего дня."""
    начало = None if period.start is None else datetime.combine(period.start, time.min, UTC)
    конец = (
        None
        if period.end is None
        else datetime.combine(period.end + timedelta(days=1), time.min, UTC)
    )
    return начало, конец


def _read(token: str, period: registry_period.Period) -> tuple[model_usage.UsageRow, ...]:
    начало, конец = _bounds(period)
    return model_usage.read(token, start=начало, end=конец)


def _render(conf: Settings) -> tuple[str, int]:
    lang = ui_lang.request_lang(conf.ui_lang)
    period = registry_period.read(request.args, today=date.today())
    previous = registry_period.shift(period, -1)
    token = auth.current_session_token()
    failed = False
    now_rows: tuple[model_usage.UsageRow, ...] = ()
    before_rows: tuple[model_usage.UsageRow, ...] | None = None
    try:
        now_rows = _read(token, period)
        before_rows = None if previous is None else _read(token, previous)
    except DbError as exc:
        note_target_mismatch(exc)
        _log.warning("usage: расход модели не прочитан (%s)", type(exc).__name__)
        failed = True

    total = usage_view.totals(now_rows)
    people = usage_view.by_person(now_rows)
    before = None if before_rows is None else usage_view.totals(before_rows)
    base = f"{request.script_root}{section('users').path}"

    def select(**изменения: str) -> str:
        параметры = {"tab": TAB_USAGE, **period.params(), "lang": lang, **изменения}
        return f"{base}?{urlencode({к: з for к, з in параметры.items() if з})}"

    hidden = {"tab": TAB_USAGE, "lang": lang}
    return (
        render_template(
            "usage/page.html",
            failed=failed,
            period=period,
            period_title=registry_view.period_title(period, lang),
            period_prev=registry_view.period_link(period, -1, select),
            period_next=registry_view.period_link(period, 1, select),
            period_quick=registry_view.period_quick(period, date.today(), lang, select),
            period_hidden=hidden,
            period_action=base,
            total=total,
            delta=usage_view.delta(total, before),
            has_previous=before is not None,
            days=usage_view.by_day(now_rows, start=period.start, end=period.end),
            kinds=usage_view.by_kind(now_rows),
            known_kinds=KINDS,
            people=people,
            inspections=usage_view.by_inspection(now_rows),
            kind_label=lambda line: (
                t(f"usage.kind.{line.key}", lang) if f"usage.kind.{line.key}" in TEXTS else line.key
            ),
            person_label=lambda line: line.label or t("usage.person.unknown", lang),
            inspection_label=lambda line: line.label or t("usage.inspection.unsent", lang),
            inspection_href=lambda line: _inspection_href(line.key, lang),
            has_system_calls=any(line.key == "" for line in people),
            money=usage_view.money,
            number=usage_view.number,
            percent=usage_view.percent,
            tab=TAB_USAGE,
            has_spaces_tab=True,
            manages_spaces=True,
            has_journal_tab=_is_super(),
            has_usage_tab=True,
            link=lambda **параметры: base + (f"?{urlencode(параметры)}" if параметры else ""),
        ),
        503 if failed else 200,
    )


def _inspection_href(key: str, lang: str) -> str | None:
    """Ссылка на карточку проверки в вебе; у проверки бота до сдачи (`run_id`) её нет."""
    try:
        number = str(uuid.UUID(key))
    except ValueError:
        return None
    return f"{request.script_root}{section('registry').path}/{number}?lang={lang}"


def _is_super() -> bool:
    вошедший = auth.current_account()
    охват = None if вошедший is None else access_policy.scope_of(вошедший.role, вошедший.tenant)
    return охват is not None and охват.kind == access_policy.SUPER


def show(conf: Settings) -> FlaskResponse | tuple[str, int]:
    """GET `/users?tab=usage[&from=&to=]`. Не админу УК — 404."""
    вошедший = auth.current_account()
    if вошедший is None or not may_see(вошедший.role, вошедший.tenant):
        abort(404)
    return _render(conf)
