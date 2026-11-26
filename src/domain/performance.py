"""Окна операционной аналитики и точные сравнения без сети и базы."""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

# Единицы — часть контракта; native LFL приходит из Dodo IS и не пересчитывается.
METRICS = {
    "revenue": "currency",
    "orders": "count",
    "delivery_seconds": "seconds",
    "restaurant_cooking_seconds": "seconds",
    "stops_seconds": "seconds",
    "stops_count": "count",
    "certificates_count": "count",
}
MEANS = frozenset({"delivery_seconds", "restaurant_cooking_seconds"})
CORE_METRICS = tuple(METRICS)
STATUSES = frozenset({"complete", "partial", "unavailable"})


@dataclass(frozen=True, order=True)
class Window:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("window end precedes start")

    def json(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


def _shift_month(day: date, months: int) -> date:
    ordinal = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(ordinal, 12)
    return date(year, month0 + 1, min(day.day, calendar.monthrange(year, month0 + 1)[1]))


def comparison_windows(as_of: date) -> dict[str, Window]:
    """MTD, предыдущий месяц и прошлый год до такого же календарного дня включительно.

    В коротком месяце отсечение прижимается к последнему дню, включая 29 февраля.
    Даже 31-го числа прошлый месяц не расширяется за границы месяца.
    """
    previous = _shift_month(as_of, -1)
    year_ago = _shift_month(as_of, -12)
    return {
        "current": Window(as_of.replace(day=1), as_of),
        "mom": Window(previous.replace(day=1), previous),
        "yoy": Window(year_ago.replace(day=1), year_ago),
    }


def last_complete_day(timezones: Iterable[str], *, now: datetime | None = None) -> date:
    """Последний завершённый день во всех названных поясах, без догадки о столице."""
    stamp = now or datetime.now(UTC)
    if stamp.tzinfo is None:
        raise ValueError("now must have timezone")
    zones = tuple(timezones)
    if not zones:
        raise ValueError("source timezone required")
    return min(stamp.astimezone(ZoneInfo(zone)).date() - timedelta(days=1) for zone in zones)


@dataclass(frozen=True)
class Observation:
    country: str
    subject_id: str  # ISO-2 страны либо нормализованный 32hex код пиццерии
    metric: str
    period: Window
    value: Decimal | None = None
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    currency: str | None = None
    timezone: str = "UTC"
    source: str = "dodois"
    status: str = "complete"
    covered_units: int | None = None
    expected_units: int | None = None
    loaded_at: datetime | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z]{2}", self.country):
            raise ValueError("country must be ISO-2")
        if self.subject_id != self.country and not re.fullmatch(r"[0-9a-f]{32}", self.subject_id):
            raise ValueError("subject must be country or normalized unit id")
        if self.metric not in METRICS or self.status not in STATUSES:
            raise ValueError("unknown metric or status")
        if self.reason is not None and not re.fullmatch(r"[a-z_]{1,64}", self.reason):
            raise ValueError("safe reason code required")
        ZoneInfo(self.timezone)
        if self.currency is not None and not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be ISO-3")
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("numerator and denominator must be provided together")
        for item in (self.value, self.numerator, self.denominator):
            if item is not None and (not isinstance(item, Decimal) or not item.is_finite()):
                raise ValueError("values must be finite Decimals")
        if self.denominator is not None and self.denominator < 0:
            raise ValueError("negative denominator")
        if self.loaded_at is not None and self.loaded_at.tzinfo is None:
            raise ValueError("loaded_at must have timezone")
        for count in (self.covered_units, self.expected_units):
            if count is not None and count < 0:
                raise ValueError("negative coverage")
        if self.covered_units is not None and self.expected_units is not None:
            if self.covered_units > self.expected_units:
                raise ValueError("coverage exceeds expected units")

    @property
    def amount(self) -> Decimal | None:
        if self.status == "unavailable" or (self.metric == "revenue" and self.currency is None):
            return None
        if self.numerator is not None:
            return self.numerator / self.denominator if self.denominator else None
        return self.value


def aggregate(rows: Iterable[Observation], *, expected_units: int | None) -> Observation | None:
    """Свёртка страны из пиццерий: суммы и взвешенные средние; валюты не смешиваются."""
    data = tuple(rows)
    if not data:
        return None
    first = data[0]
    if len({(r.country, r.metric, r.period, r.currency) for r in data}) != 1:
        raise ValueError("different countries, metrics, windows or currencies")
    if len({r.subject_id for r in data}) != len(data) or any(
        r.subject_id == r.country for r in data
    ):
        raise ValueError("unique unit observations required")
    available = [r for r in data if r.amount is not None]
    value = numerator = denominator = None
    no_orders: list[Observation] = []
    reason = None
    if first.metric in MEANS:
        # Средние источника без знаменателя остаются доступны на уровне unit.
        available = [r for r in available if r.numerator is not None and r.denominator is not None]
        # Подтверждённый пустой заказный набор — известное покрытие, но не
        # среднее 0 секунд. Missing/source-average без веса сюда не попадают.
        no_orders = [
            r
            for r in data
            if r.reason == "no_orders"
            and r.value is None
            and r.numerator in (None, Decimal(0))
            and r.denominator in (None, Decimal(0))
        ]
        if available or no_orders:
            numerator = sum((r.numerator for r in available if r.numerator is not None), Decimal(0))
            denominator = sum(
                (r.denominator for r in available if r.denominator is not None), Decimal(0)
            )
        if not available and no_orders:
            reason = "no_orders"
        elif any(r.reason == "source_rounded_average" for r in available):
            reason = "source_rounded_average"
    elif available:
        value = sum((r.amount for r in available if r.amount is not None), Decimal(0))
    covered = len(available) + len(no_orders)
    complete = (
        expected_units is not None
        and expected_units > 0
        and covered == expected_units
        and all(r.status == "complete" for r in available)
    )
    stamps = [r.loaded_at for r in [*available, *no_orders] if r.loaded_at is not None]
    return Observation(
        first.country,
        first.country,
        first.metric,
        first.period,
        value,
        numerator,
        denominator,
        first.currency,
        first.timezone,
        first.source,
        "unavailable" if not available else "complete" if complete else "partial",
        covered,
        expected_units,
        min(stamps) if stamps else None,
        reason,
    )


def observation_json(row: Observation | None, *, now: datetime | None = None) -> dict[str, Any]:
    if row is None:
        return {
            "value": None,
            "status": "unavailable",
            "coverage": None,
            "loaded_at": None,
            "stale": None,
        }
    value = row.amount
    status = row.status if value is not None else "unavailable"
    if row.covered_units is not None and row.expected_units is not None:
        if row.covered_units < row.expected_units and status == "complete":
            status = "partial"
    source_country = (
        row.subject_id == row.country
        and row.source in {"dodois/finances/sales/country", "dodois/finances/sales/country/daily"}
        and row.metric in {"revenue", "orders"}
    )
    if (
        status == "complete"
        and not source_country
        and (row.covered_units is None or row.expected_units is None)
    ):
        status = "partial"
    stamp = now or datetime.now(UTC)
    stale = row.loaded_at is None or stamp - row.loaded_at > timedelta(hours=36)
    return {
        "value": str(value) if value is not None else None,
        "status": status,
        "coverage": {
            "covered_units": row.covered_units,
            "expected_units": row.expected_units,
            **({"scope": "source_country"} if source_country else {}),
        },
        "loaded_at": row.loaded_at.astimezone(UTC).isoformat() if row.loaded_at else None,
        "stale": stale,
        "source": row.source,
        "reason": row.reason
        or (
            "unknown_currency"
            if row.metric == "revenue" and row.currency is None
            else "unknown_coverage"
            if row.expected_units is None and not source_country
            else None
        ),
        "currency": row.currency,
        "aggregation": ("weighted_mean" if row.numerator is not None else "source_average")
        if row.metric in MEANS
        else "sum",
    }


def comparison_json(current: Observation | None, previous: Observation | None) -> dict[str, Any]:
    """Разность в единицах метрики; рост в процентах только при ненулевой базе."""
    result = observation_json(previous)
    result.update(delta=None, delta_pct=None, comparison_status="unavailable")
    if current is None or previous is None:
        return result
    if (current.country, current.subject_id, current.metric, current.currency) != (
        previous.country,
        previous.subject_id,
        previous.metric,
        previous.currency,
    ):
        result["comparison_status"] = (
            "currency_mismatch" if current.currency != previous.currency else "incompatible"
        )
        return result
    if observation_json(current)["status"] != "complete" or result["status"] != "complete":
        result["comparison_status"] = "partial"
        return result
    current_value, previous_value = current.amount, previous.amount
    if current_value is None or previous_value is None:
        return result
    delta = current_value - previous_value
    result["delta"] = str(delta)
    result["delta_pct"] = str(delta / abs(previous_value) * 100) if previous_value else None
    result["comparison_status"] = "complete" if previous_value else "zero_baseline"
    return result


@dataclass(frozen=True)
class NativeLfl:
    """Неизменённые значения и периоды source LFL; единица upstream не определена."""

    country: str
    subject_id: str
    query: Window
    granularity: str
    date: date
    revenue_raw: Decimal | None
    orders_raw: Decimal | None
    loaded_at: datetime | None = None
    source: str = "dodois/customer-feedback/lfl"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z]{2}", self.country):
            raise ValueError("country must be ISO-2")
        if self.subject_id != self.country and not re.fullmatch(r"[0-9a-f]{32}", self.subject_id):
            raise ValueError("subject must be country or normalized unit id")
        if self.granularity not in {"Day", "Week", "Month"}:
            raise ValueError("invalid native LFL granularity")
        for value in (self.revenue_raw, self.orders_raw):
            if value is not None and (not isinstance(value, Decimal) or not value.is_finite()):
                raise ValueError("native LFL must contain finite Decimals")
        if self.loaded_at is not None and self.loaded_at.tzinfo is None:
            raise ValueError("loaded_at must have timezone")

    def json(self) -> dict[str, Any]:
        return {
            "query": self.query.json(),
            "granularity": self.granularity,
            "date": self.date.isoformat(),
            "revenue_raw": str(self.revenue_raw) if self.revenue_raw is not None else None,
            "orders_raw": str(self.orders_raw) if self.orders_raw is not None else None,
            "unit": "source_value",
            "status": "source_period_unverified",
            "reason": "native_bucket_not_request_slice",
            "loaded_at": self.loaded_at.astimezone(UTC).isoformat() if self.loaded_at else None,
            "source": self.source,
        }


# Только однозначные страновые пояса. Для многозонных стран источник обязан
# передать фактический пояс; при отсутствии используется явно помеченный UTC.
COUNTRY_TIMEZONES = {
    "AM": "Asia/Yerevan",
    "AZ": "Asia/Baku",
    "BG": "Europe/Sofia",
    "BY": "Europe/Minsk",
    "CY": "Asia/Nicosia",
    "EE": "Europe/Tallinn",
    "GE": "Asia/Tbilisi",
    "HR": "Europe/Zagreb",
    "KG": "Asia/Bishkek",
    "LT": "Europe/Vilnius",
    "ME": "Europe/Podgorica",
    "NG": "Africa/Lagos",
    "PL": "Europe/Warsaw",
    "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade",
    "SI": "Europe/Ljubljana",
    "TJ": "Asia/Dushanbe",
    "TR": "Europe/Istanbul",
}


def country_timezone(country: str) -> tuple[str, bool]:
    zone = COUNTRY_TIMEZONES.get(country)
    return zone or "UTC", zone is None
