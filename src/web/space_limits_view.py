"""Лимиты пространства для экрана «Пространства» (D759 п.5, #1670).

Собирает то, что рисует раздел «Лимиты» карточки пространства и заметка админу партнёра:
действующие лимиты, расход за календарный месяц (UTC) и уровень (`ok` / `warn` от 80 % /
`over`). Правило — `domain.space_limits`, деньги — `recognize.spend_cap`; здесь только
сборка. Решений о правах здесь нет: кто видит и кто правит, решают `users_page` и маршрут.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import psycopg

from src.db import space_limits
from src.db.errors import DbError
from src.domain.space_limits import Limits, effective, month_start, spend_level
from src.recognize import spend_cap


@dataclass(frozen=True)
class LimitView:
    """Лимиты одного пространства и его расход за месяц."""

    code: str
    limits: Limits
    #: Строки настроек нет — показаны умолчания партнёра.
    is_default: bool
    #: Расход за месяц, $; `None` — не удалось прочитать.
    spent: Decimal | None
    #: Часть расхода по моделям без цены в сумму не вошла.
    partial: bool
    level: str
    updated_by: str | None
    updated_at: datetime | None


def build(code: str, *, now: datetime | None = None) -> LimitView | None:
    """Вид лимитов пространства; `None` — база не ответила (экран скажет об этом словами)."""
    moment = now or datetime.now(UTC)
    try:
        row = space_limits.stored_all().get(code)
        spent, partial = spend_cap.cost_of(space_limits.month_spend(code, month_start(moment)))
    except (DbError, psycopg.Error):
        return None
    limits = effective(code, None if row is None else row.limits)
    return LimitView(
        code=code,
        limits=limits,
        is_default=row is None,
        spent=spent,
        partial=partial,
        level=spend_level(spent, limits.monthly_spend_usd),
        updated_by=None if row is None else row.updated_by,
        updated_at=None if row is None else row.updated_at,
    )


def parse_inspections(raw: str) -> int | None:
    """Поле «проверок на пиццерию»: пусто — без лимита; не целое — `ValueError`."""
    text = (raw or "").strip()
    return int(text) if text else None


def parse_spend(raw: str) -> Decimal | None:
    """Поле «потолок, $»: пусто — без потолка; запятая как точка; не число — `ValueError`."""
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(raw) from exc
    if not value.is_finite():
        raise ValueError(raw)
    return value
