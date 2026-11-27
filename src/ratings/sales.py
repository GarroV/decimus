"""Единые группы источников и каналы продаж для «Качества» и MCP."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from src.db import dodois_metrics
from src.domain import quality as q

_APP_SITE = frozenset({"mobileapp", "website", "app", "web", "site"})


def _group(source: str) -> str:
    low = source.lower()
    if "aggregator" in low:
        return "aggregators"
    return "app_site" if re.sub(r"[^a-z]", "", low) in _APP_SITE else "other"


def sales_channel(name: str) -> str:
    low = name.lower()
    if "dine" in low:
        return "dine_in"
    if "take" in low or "pickup" in low:
        return "takeaway"
    return "delivery" if "deliver" in low else "other"


@dataclass(frozen=True)
class SalesTotals:
    """Продажи из одних строк для страницы «Качество» и MCP."""

    orders: q.Orders
    revenue: dict[str, Decimal]
    revenue_by_source: dict[str, Decimal]
    channel_orders: dict[str, int]
    source_orders: dict[str, int]


def sales_totals(
    sales: Sequence[dodois_metrics.UnitSales], *, aggregator_orders: int = 0
) -> SalesTotals:
    """Те же группы источников, каналы и резерв заказов агрегаторов для обоих входов."""
    groups: dict[str, int] = defaultdict(int)
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    sources: dict[str, Decimal] = defaultdict(Decimal)
    channel_orders: dict[str, int] = defaultdict(int)
    source_orders: dict[str, int] = defaultdict(int)
    for row in sales:
        channel = sales_channel(row.sales_channel)
        groups[_group(row.order_source)] += row.orders
        revenue[channel] += row.revenue
        sources[row.order_source] += row.revenue
        channel_orders[channel] += row.orders
        source_orders[row.order_source] += row.orders
    orders = q.Orders(
        groups["aggregators"] or aggregator_orders, groups["app_site"], groups["other"]
    )
    return SalesTotals(
        orders, dict(revenue), dict(sources), dict(channel_orders), dict(source_orders)
    )
