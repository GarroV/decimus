"""Месячные оценки клиентов и журнал их сбора для выбранного среза рейтингов."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .dodois_metrics import _rows, _unit_rows


@dataclass(frozen=True)
class MonthlyKr:
    country: str
    unit: str
    name: str
    month: date
    dine_avg: Decimal | None
    dine_count: int
    delivery_avg: Decimal | None
    delivery_count: int


@dataclass(frozen=True)
class KrLoad:
    country: str
    last_ok: datetime | None
    failed: bool


def monthly(countries: Sequence[str], begin: date, end: date) -> list[MonthlyKr]:
    """Один запрос на весь срез, без усреднения средних и без отдельных отзывов."""
    if not countries or begin > end:
        return []
    rows = _unit_rows(
        "select u.country_code, k.dodo_id, u.name, k.month, k.dine_in_avg, "
        "k.dine_in_count, k.delivery_avg, k.delivery_count "
        "from dodois.unit_kr_month k join source_units u on u.dodo_id=k.dodo_id "
        "where u.country_code=any(%s) and k.month between %s and %s "
        "order by u.country_code,u.name,k.month",
        (list(countries), begin, end),
    )
    return [MonthlyKr(*r) for r in rows]


def loads(countries: Sequence[str]) -> list[KrLoad]:
    """Только KR: сбой другого вида Dodo IS не выдаётся за сбой клиентских оценок."""
    if not countries:
        return []
    rows = _rows(
        "select distinct on (country) country, "
        "(select max(finished_at) from dodois.metric_loads o "
        "where o.country=l.country and o.kind='kr' and o.ok), not ok "
        "from dodois.metric_loads l where kind='kr' and country=any(%s) "
        "and finished_at is not null order by country,started_at desc,id desc",
        (list(countries),),
    )
    return [KrLoad(*r) for r in rows]


def latest_month(countries: Sequence[str]) -> date | None:
    if not countries:
        return None
    rows = _unit_rows(
        "select max(k.month) from dodois.unit_kr_month k "
        "join source_units u on u.dodo_id=k.dodo_id where u.country_code=any(%s)",
        (list(countries),),
    )
    return rows[0][0] if rows else None
