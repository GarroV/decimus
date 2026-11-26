"""Actual country sales by day; source gaps are never distributed from monthly totals."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from src.db import performance as store
from src.domain.country_currency import currency_of
from src.domain.performance import Observation, Window

from .client import Response

SOURCE = "dodois/finances/sales/country/daily"


def collect_finance(
    country: str, period: Window, timezone: str, get: Callable[[str, dict[str, str]], Response]
) -> int:
    """At most four 10-day requests per monthly window, with overlapping singleton tails."""
    days: dict[date, tuple[Decimal, Decimal]] = {}
    start = period.start
    while start <= period.end:
        end = min(start + timedelta(days=9), period.end)
        first = start if start < end else start - timedelta(days=1)
        response = get(
            f"/dodopizza/{country.lower()}/finances/sales/country/daily",
            {"fromDate": first.isoformat(), "toDate": end.isoformat()},
        )
        if response.status != 200 or not isinstance(response.body, dict):
            raise ValueError("daily sales refused")
        result = response.body.get("result")
        if not isinstance(result, list):
            raise ValueError("daily sales shape")
        for raw in result:
            if not isinstance(raw, dict):
                raise ValueError("daily sales row")
            day = date.fromisoformat(str(raw.get("date", "")).split("T")[0])
            if not period.start <= day <= period.end:
                continue
            try:
                values = tuple(Decimal(str(raw[key])) for key in ("sales", "ordersCount"))
            except (KeyError, InvalidOperation) as exc:
                raise ValueError("daily sales values") from exc
            if not all(value.is_finite() for value in values):
                raise ValueError("daily sales nonfinite")
            if day in days and days[day] != values:
                raise ValueError("conflicting daily sales")
            days[day] = values
        start = end + timedelta(days=1)
    now = datetime.now(UTC)
    rows = []
    for day, values in sorted(days.items()):
        currency = "BGN" if country == "BG" and day < date(2026, 1, 1) else currency_of(country)
        for metric, value in zip(("revenue", "orders"), values, strict=True):
            rows.append(
                Observation(
                    country,
                    country,
                    metric,
                    Window(day, day),
                    value=value,
                    currency=currency if metric == "revenue" else None,
                    timezone=timezone,
                    source=SOURCE,
                    loaded_at=now,
                )
            )
    return store.upsert_observations(rows)
