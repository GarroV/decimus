"""Продажи пиццерий Dodo IS: разбор источника и канала, заказы по группам, выручка, средний чек.

Чистые функции без базы. Один источник правды для страницы «Качество»
(`src/web/quality_data.py`) и инструмента `sales_summary` (`src/mcp/sales_read.py`): оба сводят
строки `dodois.unit_sales_month` одними и теми же правилами, поэтому числа экрана и ответа
инструмента не расходятся.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Protocol

from .quality import Orders

#: Источники заказа «приложение и сайт»; всё, что не агрегатор и не они, — `other`.
_APP_SITE = frozenset({"mobileapp", "website", "app", "web", "site"})


class SaleRow(Protocol):
    """Строка продаж пиццерии за месяц: источник заказа и канал, заказы и выручка."""

    @property
    def order_source(self) -> str: ...
    @property
    def sales_channel(self) -> str: ...
    @property
    def orders(self) -> int: ...
    @property
    def revenue(self) -> Decimal: ...


def order_group(source: str) -> str:
    """Источник заказа → `aggregators`, `app_site` или `other`."""
    low = source.lower()
    if "aggregator" in low:
        return "aggregators"
    return "app_site" if re.sub(r"[^a-z]", "", low) in _APP_SITE else "other"


def sales_channel(name: str) -> str:
    """Канал продаж → `dine_in`, `takeaway`, `delivery` или `other`."""
    low = name.lower()
    if "dine" in low:
        return "dine_in"
    if "take" in low or "pickup" in low:
        return "takeaway"
    return "delivery" if "deliver" in low else "other"


def unit_orders(sales: Iterable[SaleRow], aggregator_orders: int) -> Orders:
    """Заказы пиццерии по группам. Агрегаторов в продажах нет — берётся их собственный счёт."""
    by_group: dict[str, int] = defaultdict(int)
    for row in sales:
        by_group[order_group(row.order_source)] += row.orders
    return Orders(
        by_group["aggregators"] or aggregator_orders, by_group["app_site"], by_group["other"]
    )


def revenue_by_channel(sales: Iterable[SaleRow]) -> dict[str, Decimal]:
    """Выручка по каналам (`sales_channel`); сумма значений — вся выручка."""
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    for row in sales:
        revenue[sales_channel(row.sales_channel)] += row.revenue
    return dict(revenue)


def avg_check(revenue: Decimal, orders: int) -> Decimal | None:
    """Средний чек: выручка на заказ; заказов нет — `None`, а не ноль."""
    return revenue / orders if orders else None


def delta_pct(now: Decimal | None, before: Decimal | None) -> Decimal | None:
    """Движение в процентах от прошлого значения, как `delta_percent` экрана; базы нет — `None`."""
    if now is None or not before:
        return None
    return (now - before) / before * 100
