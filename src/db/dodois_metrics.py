"""Чтение данных Dodo IS для страницы «Качество» (D671, миграция `0105`): продажи, агрегаторы, КР.

Дверь для веба: всё, что страница показывает из собранного ботом
(`src/bot/dodois_metrics_loader.py`), берётся отсюда. Страна — через
`ratings.units.country_code`, месяц — первое число. Запись — `src/db/dodois_metrics_store.py`.
Читает роль приложения; заслона по охвату нет намеренно: рейтинги видят все (D327), а здесь те
же агрегаты по пиццериям.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg

from src.domain.dodois_metrics import KINDS, rating_month

from .config import check_environment
from .errors import RatingsError
from .pool import connection


@dataclass(frozen=True)
class UnitSales:
    dodo_id: str
    order_source: str
    sales_channel: str
    orders: int
    revenue: Decimal
    currency: str | None


@dataclass(frozen=True)
class UnitAggregatorOrders:
    dodo_id: str
    aggregator: str
    orders: int
    revenue: Decimal | None  # выручки по агрегатору Dodo IS не отдаёт: всегда `None`


@dataclass(frozen=True)
class UnitKr:
    dodo_id: str
    dine_in_avg: Decimal | None
    dine_in_count: int
    delivery_avg: Decimal | None
    delivery_count: int


@dataclass(frozen=True)
class UnitRatingPeriod:
    dodo_id: str
    kind: str
    period_from: date
    period_to: date
    rate: Decimal
    publish_status: str | None
    checkups: int | None


@dataclass(frozen=True)
class LoadState:
    country_code: str
    last_ok_at: datetime | None
    last_error: str | None


def _rows(sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    try:
        with connection(check_environment().dsn) as conn:
            return conn.execute(sql, params).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Данные Dodo IS не прочитались: база отказала ({exc.__class__.__name__})"
        ) from exc


def unit_sales(country_code: str, month: date) -> list[UnitSales]:
    """Продажи пиццерий страны за месяц по источнику заказа и каналу."""
    rows = _rows(
        "select s.dodo_id, s.order_source, s.sales_channel, s.orders, s.revenue, s.currency "
        "from dodois.unit_sales_month s join ratings.units u on u.dodo_id = s.dodo_id "
        "where u.country_code = %s and s.month = %s "
        "order by s.dodo_id, s.order_source, s.sales_channel",
        (country_code, month),
    )
    return [UnitSales(*r) for r in rows]


def unit_aggregator_orders(country_code: str, month: date) -> list[UnitAggregatorOrders]:
    """Заказы пиццерий страны из агрегаторов за месяц."""
    rows = _rows(
        "select a.dodo_id, a.aggregator, a.orders, a.revenue "
        "from dodois.unit_aggregator_month a join ratings.units u on u.dodo_id = a.dodo_id "
        "where u.country_code = %s and a.month = %s order by a.dodo_id, a.aggregator",
        (country_code, month),
    )
    return [UnitAggregatorOrders(*r) for r in rows]


def unit_kr(country_code: str, month: date) -> list[UnitKr]:
    """Оценки клиентов пиццерий страны за месяц (шкала 0–5, зал и доставка)."""
    rows = _rows(
        "select k.dodo_id, k.dine_in_avg, k.dine_in_count, k.delivery_avg, k.delivery_count "
        "from dodois.unit_kr_month k join ratings.units u on u.dodo_id = k.dodo_id "
        "where u.country_code = %s and k.month = %s order by k.dodo_id",
        (country_code, month),
    )
    return [UnitKr(*r) for r in rows]


def unit_rating_periods(country_code: str, month: date) -> list[UnitRatingPeriod]:
    """Оценки РКО и РС пиццерий страны за месяц и число проверок в периодах.

    РКО — недели, начавшиеся в месяце; РС — периоды, большинство дней которых в месяце
    (`rating_month`: границы РС не календарные). `kind` — `rko` или `rs`; `checkups` — `None`,
    если счёта проверок за период нет.
    """
    rows = _rows(
        "select r.dodo_id, r.kind, r.period_from, r.period_to, r.rate, r.publish_status, "
        "c.checkups from dodois.unit_rating_period r "
        "join ratings.units u on u.dodo_id = r.dodo_id "
        "left join dodois.unit_checkup_period c on c.dodo_id = r.dodo_id and c.kind = r.kind "
        "and c.period_from = r.period_from "
        "where u.country_code = %s "
        "and r.period_from >= (%s::date - interval '1 month')::date "
        "and r.period_from < (%s::date + interval '1 month')::date "
        "order by r.dodo_id, r.kind, r.period_from",
        (country_code, month, month),
    )
    periods = [UnitRatingPeriod(*r) for r in rows]
    return [p for p in periods if rating_month(p.kind, p.period_from, p.period_to) == month]


def months_with_data(country_code: str) -> list[date]:
    """Месяцы, за которые у страны есть хоть какие-то данные; свежие первыми."""
    rows = _rows(
        "select month from ("
        " select s.month from dodois.unit_sales_month s"
        "  join ratings.units u on u.dodo_id = s.dodo_id where u.country_code = %s"
        " union select a.month from dodois.unit_aggregator_month a"
        "  join ratings.units u on u.dodo_id = a.dodo_id where u.country_code = %s"
        " union select k.month from dodois.unit_kr_month k"
        "  join ratings.units u on u.dodo_id = k.dodo_id where u.country_code = %s"
        " union select date_trunc('month', p.period_from)::date from dodois.unit_rating_period p"
        "  join ratings.units u on u.dodo_id = p.dodo_id where u.country_code = %s"
        ") m order by month desc",
        (country_code, country_code, country_code, country_code),
    )
    return [r[0] for r in rows]


def load_states() -> list[LoadState]:
    """Свежесть сбора по странам: когда удалось всё и какая ошибка у того, что не удалось.

    `last_ok_at` — самое раннее из «последних удачных» по трём видам данных (страна свежа
    настолько, насколько свеж самый старый вид; нет хоть одного вида — `None`).
    `last_error` — ошибка последней загрузки вида, если эта загрузка не удалась.
    """
    rows = _rows(
        "select distinct on (country, kind) country, kind, ok, error, "
        "  (select max(finished_at) from dodois.metric_loads o "
        "   where o.country = l.country and o.kind = l.kind and o.ok) "
        "from dodois.metric_loads l where finished_at is not null "
        "order by country, kind, started_at desc",
        (),
    )
    by_country: dict[str, dict[str, tuple[bool, str | None, datetime | None]]] = {}
    for country, kind, ok, error, last_ok in rows:
        by_country.setdefault(country, {})[kind] = (ok, error, last_ok)
    states: list[LoadState] = []
    for country in sorted(by_country):
        kinds = by_country[country]
        oks = [kinds[k][2] if k in kinds else None for k in KINDS]
        last_ok = None if any(o is None for o in oks) else min(o for o in oks if o is not None)
        errors = [kinds[k][1] or "failed" for k in KINDS if k in kinds and not kinds[k][0]]
        states.append(LoadState(country, last_ok, errors[0] if errors else None))
    return states
