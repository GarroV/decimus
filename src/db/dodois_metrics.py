"""Метрики Dodo IS по пиццериям: заказы, выручка, КР — заглушка до сборщика.

Контракт зафиксирован: настоящий модуль приходит со сборщиком и заменяет этот файл при
слиянии; сигнатуры ниже не менять. Пока сборщика нет, все чтения отдают пустое, и экран
«Качество» честно пишет «ещё не собрано» (`docs/21-quality.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class UnitSales:
    """Заказы и выручка пиццерии за месяц по источнику заказа и каналу продаж."""

    dodo_id: str
    order_source: str
    sales_channel: str
    orders: int
    revenue: Decimal
    currency: str | None


@dataclass(frozen=True)
class UnitAggregatorOrders:
    """Заказы и выручка пиццерии за месяц через один агрегатор."""

    dodo_id: str
    aggregator: str
    orders: int
    revenue: Decimal


@dataclass(frozen=True)
class UnitKr:
    """Клиентский рейтинг пиццерии за месяц: средние и число оценок в зале и в доставке."""

    dodo_id: str
    dine_in_avg: Decimal | None
    dine_in_count: int
    delivery_avg: Decimal | None
    delivery_count: int


@dataclass(frozen=True)
class LoadState:
    """Состояние последнего сбора по стране."""

    country_code: str
    last_ok_at: datetime | None
    last_error: str | None


@dataclass(frozen=True)
class UnitRatingPeriod:
    """РКО (неделя) или РС (полумесяц) пиццерии из Dodo IS: оценка и число проверок периода."""

    dodo_id: str
    kind: str  # 'rko' | 'rs'
    period_from: date
    period_to: date
    rate: Decimal
    publish_status: str | None
    checkups: int | None


def unit_sales(country_code: str, month: date) -> list[UnitSales]:
    """Заказы и выручка пиццерий страны за месяц."""
    return []


def unit_aggregator_orders(country_code: str, month: date) -> list[UnitAggregatorOrders]:
    """Заказы пиццерий страны за месяц по агрегаторам."""
    return []


def unit_kr(country_code: str, month: date) -> list[UnitKr]:
    """КР пиццерий страны за месяц."""
    return []


def unit_rating_periods(country_code: str, month: date) -> list[UnitRatingPeriod]:
    """Периоды РКО и РС пиццерий страны, начавшиеся в месяце."""
    return []


def load_states() -> list[LoadState]:
    """Состояние сбора по странам."""
    return []


def months_with_data(country_code: str) -> list[date]:
    """Месяцы (первые числа), за которые у страны есть данные Dodo IS."""
    return []
