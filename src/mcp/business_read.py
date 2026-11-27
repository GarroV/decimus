"""Продажи и месячное «Качество» через MCP: общий расчёт с вебом, только чтение."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any

from src.db import agg_store, dodois_metrics
from src.db import ratings_read as read
from src.db.errors import ConfigError, DbError
from src.db.reach import Reach, reach_of
from src.domain import quality as q
from src.domain.country_currency import currency_of
from src.ratings import quality_data as quality

from .db_target import config_refusal
from .errors import ToolError

MAX_LIMIT = 200


@contextmanager
def _reading() -> Iterator[None]:
    try:
        yield
    except ConfigError as exc:
        raise config_refusal(
            exc, "Данные не прочитаны: база на этом сервере не подключена"
        ) from None
    except DbError as exc:
        raise ToolError("Данные не прочитаны: база недоступна. Это не отсутствие данных") from exc


def _month(value: str | None) -> date:
    today = date.today().replace(day=1)
    if value is None:
        return today
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", value):
            raise ValueError
        found = date.fromisoformat(value + "-01")
        if found.year < 2001 or found > today:
            raise ValueError
        return found
    except (TypeError, ValueError):
        raise ToolError("month: YYYY-MM, начиная с 2001 года, не в будущем") from None


def _shift(month: date, step: int) -> date:
    number = month.year * 12 + month.month - 1 + step
    return date(number // 12, number % 12 + 1, 1)


def _scope(tenant: str, country: str | None) -> tuple[Reach, tuple[str, ...]]:
    reach = reach_of(tenant)
    if reach.countries == ():
        return reach, ()
    codes = tuple(
        sorted(
            r.code
            for r in read.countries()
            if r.is_imf and (reach.countries is None or r.code in reach.countries)
        )
    )
    if country is not None:
        code = country.strip().upper()
        if code not in codes:
            raise ToolError("Страна не найдена или недоступна в вашем охвате")
        codes = (code,)
    return reach, codes


def _page(limit: int, offset: int, unit: str | None) -> None:
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ToolError(f"limit: целое число от 1 до {MAX_LIMIT}")
    if type(offset) is not int or not 0 <= offset <= 100_000:
        raise ToolError("offset: целое число от 0 до 100000")
    if unit is not None and (not isinstance(unit, str) or not 1 <= len(unit.strip()) <= 200):
        raise ToolError("unit: id пиццерии или часть названия, от 1 до 200 символов")


def _matches(uid: str, name: str, query: str | None) -> bool:
    return (
        not query
        or query.strip().casefold() in (uid.casefold(),)
        or query.strip().casefold() in name.casefold()
    )


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def _change(value: Any, before: Any) -> dict[str, str | None]:
    if value is None or before is None:
        return {"absolute": None, "percent": None}
    now, old = Decimal(str(value)), Decimal(str(before))
    delta = now - old
    return _json(
        {
            "absolute": delta,
            "percent": (delta / abs(old) * 100).quantize(Decimal(".01")) if old else None,
        }
    )


def _comparisons(
    now: dict[str, Any], previous: dict[str, Any], year: dict[str, Any], *, complete: bool
) -> dict[str, Any]:
    return {
        key: {
            "month": before["month"],
            "values": before,
            "change": {
                field: _change(now.get(field), before.get(field))
                for field in ("revenue", "orders", "average_check")
            }
            if complete and now.get("currency") == before.get("currency")
            else None,
        }
        for key, before in (("previous_month", previous), ("previous_year", year))
    }


def _sales_values(
    rows: Sequence[dodois_metrics.UnitSales],
    aggs: Sequence[dodois_metrics.UnitAggregatorOrders],
    *,
    code: str,
    month: date,
) -> dict[str, Any]:
    currencies = {r.currency.strip().upper() for r in rows if r.currency and r.currency.strip()}
    if len(currencies) > 1:
        raise ToolError(f"В стране {code} за {month:%Y-%m} разные валюты: суммы не объединяются")
    currency = next(iter(currencies), currency_of(code))
    totals = quality.sales_totals(rows, aggregator_orders=sum(r.orders for r in aggs))
    money = bool(rows) and currency is not None
    revenue = sum(totals.revenue.values(), Decimal(0)) if money else None
    covered_orders = sum(r.orders for r in rows)
    # Quality applies the aggregator fallback per unit before adding country totals.
    unit_orders = [
        quality.sales_totals(
            [r for r in rows if r.dodo_id == uid],
            aggregator_orders=sum(r.orders for r in aggs if r.dodo_id == uid),
        ).orders
        for uid in {r.dodo_id for r in rows} | {r.dodo_id for r in aggs}
    ]
    orders = q.Orders(
        sum(r.aggregators for r in unit_orders),
        sum(r.app_site for r in unit_orders),
        sum(r.other for r in unit_orders),
    )
    groups = {"aggregators": orders.aggregators, "app_site": orders.app_site, "other": orders.other}
    return _json(
        {
            "month": month.strftime("%Y-%m"),
            "available": bool(rows),
            "currency": currency,
            "revenue": revenue,
            "orders": orders.total if rows or aggs else None,
            "orders_with_revenue": covered_orders if rows else None,
            "average_check": (revenue / covered_orders).quantize(Decimal(".01"))
            if revenue is not None and covered_orders
            else None,
            "channels": {
                channel: {
                    "orders": totals.channel_orders.get(channel, 0),
                    "revenue": totals.revenue.get(channel) if money else None,
                    "average_check": (
                        totals.revenue[channel] / totals.channel_orders[channel]
                    ).quantize(Decimal(".01"))
                    if money and totals.channel_orders.get(channel)
                    else None,
                }
                for channel in sorted(totals.revenue)
            },
            "source_groups": {
                name: {"orders": count, "share": q.share(count, orders.total)}
                for name, count in groups.items()
            },
            "sources": {
                source: {
                    "orders": count,
                    "share": q.share(count, covered_orders),
                    "revenue": totals.revenue_by_source.get(source) if money else None,
                }
                for source, count in sorted(totals.source_orders.items())
            },
        }
    )


def sales_summary(
    *,
    tenant: str,
    month: str | None = None,
    country: str | None = None,
    unit: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """Месячные продажи и две базы сравнения; нет денежной суммы по сети."""
    selected = _month(month)
    _page(limit, offset, unit)
    periods = (selected, _shift(selected, -1), _shift(selected, -12))
    complete = selected < date.today().replace(day=1)
    with _reading():
        _, codes = _scope(tenant, country)
        if not codes:
            return {"status": "no_countries", "countries": []}
        names = {r.dodo_id: r.name for r in agg_store.units(codes)}
        loads = {
            r.country: r
            for r in dodois_metrics.kind_loads()
            if r.kind == "sales" and r.country in codes
        }
        countries = []
        all_units = []
        for code in codes:
            snapshots = []
            for period in periods:
                rows = [
                    r
                    for r in dodois_metrics.unit_sales(code, period)
                    if _matches(r.dodo_id, names.get(r.dodo_id, r.dodo_id), unit)
                ]
                aggs = [
                    r
                    for r in dodois_metrics.unit_aggregator_orders(code, period)
                    if _matches(r.dodo_id, names.get(r.dodo_id, r.dodo_id), unit)
                ]
                ids = sorted({r.dodo_id for r in rows} | {r.dodo_id for r in aggs})
                snapshots.append(
                    (
                        _sales_values(rows, aggs, code=code, month=period),
                        {
                            uid: _sales_values(
                                [r for r in rows if r.dodo_id == uid],
                                [r for r in aggs if r.dodo_id == uid],
                                code=code,
                                month=period,
                            )
                            for uid in ids
                        },
                    )
                )
            now, before, year = (s[0] for s in snapshots)
            load = loads.get(code)
            countries.append(
                {
                    "country": code,
                    **now,
                    "comparison": _comparisons(now, before, year, complete=complete),
                    "last_loaded_at": load.ok_at.isoformat() if load and load.ok_at else None,
                    "last_attempt_ok": load.attempt_ok if load else None,
                }
            )
            ids = sorted(set().union(*(set(s[1]) for s in snapshots)))
            for uid in ids:
                values = [
                    snapshot[1].get(uid) or _sales_values([], [], code=code, month=period)
                    for snapshot, period in zip(snapshots, periods, strict=True)
                ]
                all_units.append(
                    {
                        "unit_id": uid,
                        "name": names.get(uid, uid),
                        "country": code,
                        **values[0],
                        "comparison": _comparisons(*values, complete=complete),
                    }
                )
    return {
        "status": "ok" if any(c["available"] for c in countries) else "no_data",
        "month": selected.strftime("%Y-%m"),
        "incomplete_month": not complete,
        "countries": countries,
        "units": all_units[offset : offset + limit],
        "total_units": len(all_units),
        "returned": len(all_units[offset : offset + limit]),
        "next_offset": offset + limit if offset + limit < len(all_units) else None,
        "source": (
            "Dodo IS monthly cache; same sales grouping as Quality. Countries are never summed."
        ),
        "note": "Average check uses orders covered by sales revenue. Shares are fractions 0–1. "
        "Comparisons are calendar months, not LFL. Current-month changes are suppressed "
        "because comparison months are complete; null means missing, not zero.",
    }


def _quality_values(
    row: quality.CountryHealth | quality.UnitHealth, *, currency: str | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "values": {k: v for k, v in row.values.items() if k != "audit"},
        "rating_source": row.rating_source,
        "currency": row.currency if isinstance(row, quality.CountryHealth) else currency,
        "orders": {**asdict(row.orders), "total": row.orders.total},
        "aggregators": [{**asdict(a), "score5": a.score5} for a in row.aggs],
    }
    if isinstance(row, quality.CountryHealth):
        result.update(
            customer_ratings=asdict(row.kr),
            maps=[asdict(m) for m in row.maps],
            dodois_status=row.dodois,
        )
    else:
        result.update(
            customer_ratings=asdict(row.kr_parts) if row.kr_parts else None,
            maps=[{"provider": p, "score": s, "reviews": n} for p, s, n in row.maps],
            maps_carried_from=dict(row.maps_carried),
        )
    return _json(result)


def quality_summary(
    *,
    tenant: str,
    month: str | None = None,
    country: str | None = None,
    unit: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, object]:
    """РС/РКО, КР, Google/Яндекс, агрегаторы и итог ровно как на странице «Качество»."""
    selected = _month(month)
    _page(limit, offset, unit)
    periods = (selected, _shift(selected, -1), _shift(selected, -12))
    with _reading():
        reach, codes = _scope(tenant, country)
        if not codes:
            return {"status": "no_countries", "countries": []}
        loaded = [quality.load_month(reach, codes, period, with_audit=False) for period in periods]
        countries, units = [], []
        for code in codes:
            rows = []
            for snapshot in loaded:
                row = snapshot[code]
                if unit:
                    row = quality._country(
                        code,
                        [u for u in row.units if _matches(u.dodo_id, u.name, unit)],
                        row.currency,
                        row.dodois,
                    )
                rows.append(row)
            now, before, year = rows
            countries.append(
                {
                    "country": code,
                    **_quality_values(now),
                    "comparison": {
                        "previous_month": _quality_values(before),
                        "previous_year": _quality_values(year),
                    },
                }
            )
            previous_units = [({u.dodo_id: u for u in row.units}, row.currency) for row in rows[1:]]
            for row in sorted(now.units, key=lambda u: (u.name.casefold(), u.dodo_id)):
                units.append(
                    {
                        "unit_id": row.dodo_id,
                        "name": row.name,
                        "country": code,
                        **_quality_values(row, currency=now.currency),
                        "comparison": {
                            key: _quality_values(values[row.dodo_id], currency=currency)
                            if row.dodo_id in values
                            else None
                            for key, (values, currency) in zip(
                                ("previous_month", "previous_year"), previous_units, strict=True
                            )
                        },
                    }
                )
    return {
        "status": "ok" if units else "no_data",
        "month": selected.strftime("%Y-%m"),
        "comparison_months": {
            "previous_month": periods[1].strftime("%Y-%m"),
            "previous_year": periods[2].strftime("%Y-%m"),
        },
        "incomplete_month": selected == date.today().replace(day=1),
        "countries": countries,
        "units": units[offset : offset + limit],
        "total_units": len(units),
        "returned": len(units[offset : offset + limit]),
        "next_offset": offset + limit if offset + limit < len(units) else None,
        "source": "Same monthly calculation and cache as Quality. RS/RKO: 0–100; "
        "customer/maps/normalized aggregator/overall scores: 0–5; shares: 0–1. "
        "Aggregators also include their native scale. Inspection details: get_inspection.",
    }
