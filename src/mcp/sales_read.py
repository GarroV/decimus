"""Продажи пиццерий Dodo IS через Claude: `sales_summary` (только чтение).

Три правила.

**Числа — те же функции, что у страницы «Качество».** Строки — `db.dodois_metrics`
(`unit_sales`, `unit_aggregator_orders`), свёртка канала, источника и заказов —
`domain.sales_view`, которой пользуется и экран. Здесь отбор, охват и форма ответа, а не
своя арифметика: два «официальных» числа выручки были бы хуже одного.

**Охват — по токену**, как у `ratings_units`: партнёр видит страны своего пространства, УК —
все. Страна вне охвата отвечает тем же отказом, что неизвестная. Аргумента `tenant` у
инструмента нет — его назвал бы кто угодно.

**Деньги между валютами не складываются, неполный месяц с полным не сравнивается.** Общего
итога выручки по сети нет, только заказы. У идущего месяца сравнения пустые: дельта
неполного месяца к полному читалась бы как падение.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..db import agg_store, dodois_metrics
from ..db.errors import ConfigError as DbConfigError
from ..db.errors import DbError
from ..db.reach import reach_of
from ..domain import quality as q
from ..domain import sales_view as sv
from ..domain.dodois_metrics import KIND_SALES
from .db_target import config_refusal
from .errors import ToolError

NOT_CONNECTED = (
    "Продажи Dodo IS на этом стенде не подключены: не задана переменная окружения DATABASE_URL. "
    "Это отказ чтения, а не отсутствие продаж"
)
READ_FAILED = "Продажи не прочитались: база отказала. Это отказ чтения, а не отсутствие продаж"
NO_COUNTRIES = (
    "У этого пространства нет стран в охвате, поэтому продажи ему не показываются. "
    "Страны назначает управляющая компания"
)
BAD_COUNTRY = "country: код страны — две заглавные латинские буквы, например RS"
UNKNOWN_COUNTRY = "Страна «{code}» не найдена среди стран вашего охвата. Доступно: {known}"
BAD_MONTH = "month: формат ГГГГ-ММ, например 2026-09, получено «{text}»"
NO_DATA = "За выбранный месяц продаж нет: загрузка Dodo IS их ещё не принесла"

SOURCE_NOTE = (
    "Продажи из Dodo IS (finances/sales/units), собираются ботом ежечасно; "
    "те же числа, что на странице «Качество»"
)
SCALE = (
    "Деньги — в валюте страны, округлены до 0,01. Доли заказов и дельты — проценты, "
    "округлены до 0,01: orders_share — доля группы в заказах пиццерий"
)
MONEY_NOTE = (
    "Выручка в разных валютах не складывается: общего итога выручки по сети нет, "
    "сравнивать страны по выручке нельзя. Заказы по сети сложены (network_orders)"
)
OPEN_NOTE = (
    "Месяц ещё идёт, данные неполные: сравнения с прошлым месяцем и с тем же месяцем "
    "прошлого года не считаются (неполный месяц против полного вводит в заблуждение)"
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
_MONTH = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")
_COUNTRY = re.compile(r"[A-Z]{2}")
_CENTS = Decimal("0.01")


@contextmanager
def _sales() -> Iterator[None]:
    """Отказ окружения базы и самой базы — отказом инструмента, а не сбоем разбора."""
    try:
        yield
    except DbConfigError as exc:
        raise config_refusal(exc, NOT_CONNECTED) from None
    except DbError as exc:
        raise ToolError(READ_FAILED) from exc


def _scope(tenant: str) -> tuple[str, ...] | None:
    """Страны, которые видит пространство: `None` — все (УК), иначе страны партнёра."""
    return reach_of(tenant).countries


def _money(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(_CENTS))


def _month(text: str | None, today: date) -> date:
    if text is None:
        return today.replace(day=1)
    found = _MONTH.fullmatch(text.strip())
    if found is None:
        raise ToolError(BAD_MONTH.format(text=text))
    return date(int(found[1]), int(found[2]), 1)


def _limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ToolError(f"limit: от 1 до {MAX_LIMIT}, получено {limit}")
    return limit


def _prior(month: date, months: int) -> date:
    index = month.year * 12 + month.month - 1 - months
    year, number = divmod(index, 12)
    return date(year, number + 1, 1)


@dataclass(frozen=True)
class _Unit:
    """Пиццерия за месяц: выручка, заказы и выручка по каналам — теми же функциями, что у экрана."""

    dodo_id: str
    revenue: Decimal
    orders: q.Orders
    channels: dict[str, Decimal]
    currency: str | None


def _units(
    sales: Sequence[dodois_metrics.UnitSales], aggs: Sequence[dodois_metrics.UnitAggregatorOrders]
) -> dict[str, _Unit]:
    ids = sorted({s.dodo_id for s in sales})
    out: dict[str, _Unit] = {}
    for uid in ids:
        own = [s for s in sales if s.dodo_id == uid]
        channels = sv.revenue_by_channel(own)
        agg_total = sum(a.orders for a in aggs if a.dodo_id == uid)
        out[uid] = _Unit(
            uid,
            sum(channels.values(), q.ZERO),
            sv.unit_orders(own, agg_total),
            channels,
            next((s.currency for s in own if s.currency), None),
        )
    return out


@dataclass(frozen=True)
class _Total:
    revenue: Decimal
    orders: q.Orders
    channels: dict[str, Decimal]

    @property
    def avg_check(self) -> Decimal | None:
        return sv.avg_check(self.revenue, self.orders.total)


def _total(units: Sequence[_Unit]) -> _Total:
    channels: dict[str, Decimal] = defaultdict(Decimal)
    for u in units:
        for channel, amount in u.channels.items():
            channels[channel] += amount
    return _Total(
        sum((u.revenue for u in units), q.ZERO),
        q.Orders(
            sum(u.orders.aggregators for u in units),
            sum(u.orders.app_site for u in units),
            sum(u.orders.other for u in units),
        ),
        dict(channels),
    )


def _comparison(now: _Total, before: dict[str, _Unit], month: date) -> dict[str, object] | None:
    """Прошлый месяц страны и движение к нему; в базе его нет — `None`."""
    if not before:
        return None
    then = _total(list(before.values()))
    return {
        "month": month.isoformat(),
        "revenue": _money(then.revenue),
        "orders": then.orders.total,
        "avg_check": _money(then.avg_check),
        "revenue_delta_pct": _money(sv.delta_pct(now.revenue, then.revenue)),
        "orders_delta_pct": _money(
            sv.delta_pct(Decimal(now.orders.total), Decimal(then.orders.total))
        ),
    }


def _share(part: int, total: int) -> float | None:
    found = q.share(part, total)
    return None if found is None else _money(found * 100)


def _country_row(
    code: str,
    now: dict[str, _Unit],
    prev: dict[str, _Unit],
    year_ago: dict[str, _Unit],
    *,
    month: date,
    is_open: bool,
    loaded_at: str | None,
) -> dict[str, object]:
    total = _total(list(now.values()))
    orders = total.orders
    has_data = bool(now)
    currency = next((u.currency for u in now.values() if u.currency), None)
    return {
        "country": code,
        "currency": currency,
        "loaded_at": loaded_at,
        "units_with_data": len(now),
        "revenue": _money(total.revenue) if has_data else None,
        "orders": orders.total if has_data else None,
        "avg_check": _money(total.avg_check),
        "revenue_dine_in": _money(total.channels.get("dine_in")) if has_data else None,
        "revenue_delivery": _money(total.channels.get("delivery")) if has_data else None,
        "orders_share": {
            "aggregators": _share(orders.aggregators, orders.total),
            "app_site": _share(orders.app_site, orders.total),
            "other": _share(orders.other, orders.total),
        },
        "prev_month": None
        if is_open or not has_data
        else _comparison(total, prev, _prior(month, 1)),
        "same_month_last_year": None
        if is_open or not has_data
        else _comparison(total, year_ago, _prior(month, 12)),
    }


def _unit_row(
    unit: _Unit, *, code: str, name: str, prev: dict[str, _Unit], is_open: bool
) -> dict[str, object]:
    before = None if is_open else prev.get(unit.dodo_id)
    return {
        "unit_id": unit.dodo_id,
        "name": name,
        "country": code,
        "currency": unit.currency,
        "revenue": _money(unit.revenue),
        "orders": unit.orders.total,
        "avg_check": _money(sv.avg_check(unit.revenue, unit.orders.total)),
        "revenue_dine_in": _money(unit.channels.get("dine_in")),
        "revenue_delivery": _money(unit.channels.get("delivery")),
        "prev_month_revenue": None if before is None else _money(before.revenue),
        "revenue_delta_pct": None
        if before is None
        else _money(sv.delta_pct(unit.revenue, before.revenue)),
    }


def _loaded(loads: Sequence[dodois_metrics.KindLoad]) -> dict[str, str | None]:
    """Последняя удачная загрузка продаж по странам."""
    return {
        x.country: None if x.ok_at is None else x.ok_at.isoformat()
        for x in loads
        if x.kind == KIND_SALES
    }


def sales_summary(
    *,
    tenant: str,
    country: str | None = None,
    month: str | None = None,
    by_unit: bool = False,
    limit: int | None = None,
) -> dict[str, object]:
    today = date.today()
    asked = _month(month, today)
    cap = _limit(limit)
    if not isinstance(by_unit, bool):
        raise ToolError(f"by_unit: true или false, получено «{by_unit}»")
    code = None if country is None else country.strip()
    if code is not None and _COUNTRY.fullmatch(code) is None:
        raise ToolError(BAD_COUNTRY)
    is_open = asked >= today.replace(day=1)
    with _sales():
        only = _scope(tenant)
        if only == ():
            return {"status": "no_countries", "message": NO_COUNTRIES}
        registry = agg_store.units(only)
        known = sorted({u.country for u in registry})
        if code is not None and code not in known:
            raise ToolError(UNKNOWN_COUNTRY.format(code=code, known=", ".join(known) or "ничего"))
        codes = [code] if code else known
        loaded = _loaded(dodois_metrics.kind_loads())
        rows: list[dict[str, object]] = []
        units: list[dict[str, object]] = []
        network_orders = 0
        for c in codes:
            now = _units(
                dodois_metrics.unit_sales(c, asked), dodois_metrics.unit_aggregator_orders(c, asked)
            )
            prev: dict[str, _Unit] = {}
            year_ago: dict[str, _Unit] = {}
            if not is_open:
                month_before, year_before = _prior(asked, 1), _prior(asked, 12)
                prev = _units(
                    dodois_metrics.unit_sales(c, month_before),
                    dodois_metrics.unit_aggregator_orders(c, month_before),
                )
                year_ago = _units(
                    dodois_metrics.unit_sales(c, year_before),
                    dodois_metrics.unit_aggregator_orders(c, year_before),
                )
            network_orders += _total(list(now.values())).orders.total
            rows.append(
                _country_row(
                    c, now, prev, year_ago, month=asked, is_open=is_open, loaded_at=loaded.get(c)
                )
            )
            if by_unit:
                names = {u.dodo_id: u.name for u in registry if u.country == c}
                units.extend(
                    _unit_row(u, code=c, name=names.get(u.dodo_id, u.dodo_id[:8]), prev=prev,
                              is_open=is_open)
                    for u in sorted(now.values(), key=lambda x: (-x.revenue, x.dodo_id))
                )  # fmt: skip
    empty = all(r["units_with_data"] == 0 for r in rows)
    answer: dict[str, object] = {
        "status": "no_data" if empty else "ok",
        "month": asked.isoformat()[:7],
        "month_open": is_open,
        "countries": rows,
        "network_orders": network_orders,
        "scale": SCALE,
        "source": SOURCE_NOTE,
        "note": f"{MONEY_NOTE}. {OPEN_NOTE}" if is_open else MONEY_NOTE,
    }
    if empty:
        answer["message"] = NO_DATA
    if by_unit:
        page = units[:cap]
        answer.update(
            {
                "total_units": len(units),
                "returned": len(page),
                "truncated": len(units) > cap,
                "units": page,
            }
        )
    return answer
