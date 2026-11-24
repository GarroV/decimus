"""Строгий разбор операционных ответов Dodo IS без сети и персональных данных.

Window содержит включённые даты. Стопы переводятся из явных Local-полей в
часовой пояс запроса и обрезаются полуинтервалом местных полуночей. Полнота
стопов на левой границе API ещё не доказана, поэтому их статус всегда partial.
Средние восстанавливаются из округлённого среднего и count той же выборки.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from src.domain.country_currency import currency_of
from src.domain.performance import NativeLfl, Observation, Window


class ShapeError(ValueError):
    """Неподдерживаемая форма; сообщение не содержит значений ответа."""


def _unit(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
    ):
        raise ShapeError("invalid unitId")
    return UUID(value).hex


def _context(country: str, timezone: str, expected: list[str]) -> tuple[str, list[str]]:
    if not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2}", country):
        raise ShapeError("invalid country")
    ZoneInfo(timezone)
    units = [_unit(unit) for unit in expected]
    if len(set(units)) != len(units):
        raise ShapeError("duplicate expected unit")
    return country.upper(), units


def _rows(body: object, key: str) -> list[Mapping[str, object]]:
    if not isinstance(body, Mapping):
        raise ShapeError("invalid " + key)
    rows: object = body.get(key)
    if not isinstance(rows, list):
        raise ShapeError("invalid " + key)
    if not all(isinstance(row, Mapping) for row in rows):
        raise ShapeError("invalid row in " + key)
    return [cast(Mapping[str, object], row) for row in rows]


def _number(value: object, field: str, *, count: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ShapeError("invalid " + field)
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ShapeError("invalid " + field) from None
    if not result.is_finite() or (count and (result < 0 or result != result.to_integral_value())):
        raise ShapeError("invalid " + field)
    return result


def _indexed(
    body: object, key: str, expected: list[str],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    allowed = set(expected)
    for row in _rows(body, key):
        unit = _unit(row.get("unitId"))
        if unit not in allowed or unit in result:
            raise ShapeError("unexpected or duplicate unitId")
        result[unit] = row
    return result


def _observation(
    country: str, unit: str, metric: str, period: Window, timezone: str, source: str, *,
    value: Decimal | None = None, numerator: Decimal | None = None,
    denominator: Decimal | None = None, currency: str | None = None,
    status: str = "complete", reason: str | None = None,
) -> Observation:
    available = status != "unavailable"
    return Observation(
        country=country, subject_id=unit, metric=metric, period=period,
        timezone=timezone, source=source, covered_units=int(available), expected_units=1,
        value=value, numerator=numerator, denominator=denominator, currency=currency,
        status=status, reason=reason,
    )


def sales(body: object, country: str, period: Window, timezone: str,
          expected: list[str]) -> list[Observation]:
    """Итоги /finances/sales/units; отсутствие строки не означает нулевые продажи."""
    country, units = _context(country, timezone, expected)
    rows = _indexed(body, "result", units)
    currency = currency_of(country)
    currency_reason = None
    if country == "BG":
        if period.end < date(2026, 1, 1):
            currency = "BGN"
        elif period.start < date(2026, 1, 1):
            currency, currency_reason = None, "currency_change_within_window"
    if currency is None and currency_reason is None:
        currency_reason = "unknown_currency"
    result = []
    for unit in units:
        row = rows.get(unit)
        values = None if row is None else {
            "revenue": _number(row.get("sales"), "sales"),
            "orders": _number(row.get("ordersCount"), "ordersCount", count=True),
        }
        for metric in ("revenue", "orders"):
            reason = (
                "missing_unit" if row is None else currency_reason if metric == "revenue" else None
            )
            result.append(_observation(
                country, unit, metric, period, timezone, "dodois/finances/sales/units",
                value=values[metric] if values is not None and reason is None else None,
                currency=currency if metric == "revenue" else None,
                status="unavailable" if reason else "complete", reason=reason,
            ))
    return result


def _mean(
    body: object, country: str, period: Window, timezone: str, expected: list[str], *,
    key: str, metric: str, field: str, count: str, source: str,
) -> list[Observation]:
    country, units = _context(country, timezone, expected)
    rows = _indexed(body, key, units)
    result = []
    for unit in units:
        row = rows.get(unit)
        weight = None if row is None else _number(row.get(count), count, count=True)
        average = None
        if row is not None:
            raw = row.get(field)
            if raw is not None or weight:
                average = _number(raw, field)
                if average < 0:
                    raise ShapeError("negative " + field)
            elif field not in row:
                raise ShapeError("missing " + field)
        reason = "source_rounded_average"
        if row is None:
            reason = "missing_unit"
        elif not weight:
            reason = "no_orders"
        result.append(_observation(
            country, unit, metric, period, timezone, source,
            numerator=average * weight if average is not None and weight else None,
            denominator=weight if weight else None,
            status="complete" if weight else "unavailable", reason=reason,
        ))
    return result


def cooking(body: object, country: str, period: Window, timezone: str,
            expected: list[str]) -> list[Observation]:
    """Только ответ запроса salesChannels=DineIn, вес — filtered ordersCount."""
    return _mean(
        body, country, period, timezone, expected, key="ordersHandoverStatistics",
        metric="restaurant_cooking_seconds", field="avgCookingTime", count="ordersCount",
        source="dodois/production/orders-handover-statistics:DineIn:weighted_rounded",
    )


def delivery(body: object, country: str, period: Window, timezone: str,
             expected: list[str]) -> list[Observation]:
    """Вес deliveryOrdersCount той же исключённой выборки, не общий finances count.

    Восстановленный numerator приближён: исходное среднее округлено до секунд.
    """
    return _mean(
        body, country, period, timezone, expected, key="unitsStatistics",
        metric="delivery_seconds", field="avgDeliveryOrderFulfillmentTime",
        count="deliveryOrdersCount", source="dodois/delivery/statistics:weighted_rounded",
    )


def _local(value: object, field: str, zone: ZoneInfo) -> datetime:
    if not isinstance(value, str):
        raise ShapeError("invalid " + field)
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        raise ShapeError("invalid " + field) from None
    if "T" not in value or stamp.tzinfo is not None:
        raise ShapeError("explicit local datetime required")
    return stamp.replace(tzinfo=zone)


def stops(body: object, country: str, period: Window, timezone: str,
          expected: list[str]) -> list[Observation]:
    """Объединение Complete-стопов каналов; Redirection не прибавляется к простою.

    stops_seconds — время хотя бы одного полностью остановленного канала;
    stops_count — число Complete-событий, пересекающих окно. Не продукт-минуты.
    Даже успешный пустой ответ partial: выборка пересекающих from стопов не доказана.
    """
    country, units = _context(country, timezone, expected)
    zone = ZoneInfo(timezone)
    left = datetime.combine(period.start, time.min, zone)
    right = datetime.combine(period.end + timedelta(days=1), time.min, zone)
    intervals: dict[str, list[tuple[datetime, datetime]]] = {unit: [] for unit in units}
    seen: set[tuple[str, str]] = set()
    for row in _rows(body, "stopSalesBySalesChannels"):
        unit = _unit(row.get("unitId"))
        identity = row.get("id")
        if (unit not in intervals or not isinstance(identity, str) or not identity
                or (unit, identity) in seen):
            raise ShapeError("unexpected or duplicate stop")
        seen.add((unit, identity))
        if row.get("salesChannelName") not in {"Dine-in", "Takeaway", "Delivery"}:
            raise ShapeError("invalid salesChannelName")
        kind = row.get("channelStopType")
        if kind not in {"Complete", "Redirection"}:
            raise ShapeError("invalid channelStopType")
        start = _local(row.get("startedAtLocal"), "startedAtLocal", zone)
        if "endedAtLocal" not in row:
            raise ShapeError("missing endedAtLocal")
        end = (right if row["endedAtLocal"] is None
               else _local(row["endedAtLocal"], "endedAtLocal", zone))
        if end < start and row["endedAtLocal"] is not None:
            raise ShapeError("stop end precedes start")
        start, end = max(start, left), min(end, right)
        if kind == "Complete" and start < end:
            intervals[unit].append((start, end))
    result = []
    for unit, events in intervals.items():
        merged: list[tuple[datetime, datetime]] = []
        for start, end in sorted(events):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        # UTC subtraction preserves actual elapsed seconds across DST changes.
        seconds = sum((Decimal(str(end.timestamp() - start.timestamp()))
                       for start, end in merged), Decimal(0))
        for metric, value in (("stops_seconds", seconds), ("stops_count", Decimal(len(events)))):
            result.append(_observation(
                country, unit, metric, period, timezone,
                "dodois/production/stop-sales-channels:Complete:union_local",
                value=value, status="partial", reason="boundary_semantics_unverified",
            ))
    return result


def vouchers(body: object, country: str, period: Window, timezone: str,
             expected: list[str]) -> list[Observation]:
    """Все завершённые страницы batch; сохраняются только счётчики по unit.

    Повтор одного orderId внутри одного unit удаляется. Коллизия между unit —
    ошибка формы; issuer/courier/orderNumber и прочие поля не переносятся.
    """
    country, units = _context(country, timezone, expected)
    rows = _rows(body, "vouchers")
    if cast(Mapping[str, object], body).get("isEndOfListReached") is not True:
        raise ShapeError("incomplete vouchers pagination")
    counts = dict.fromkeys(units, 0)
    seen: dict[str, str] = {}
    for row in rows:
        unit, order = _unit(row.get("unitId")), row.get("orderId")
        if not isinstance(order, str) or not order:
            raise ShapeError("invalid orderId")
        if unit not in counts or (order in seen and seen[order] != unit):
            raise ShapeError("unexpected unit or conflicting orderId")
        if order not in seen:
            counts[unit] += 1
            seen[order] = unit
    return [_observation(
        country, unit, "certificates_count", period, timezone,
        "dodois/delivery/vouchers:dedup_order",
        value=Decimal(count),
    ) for unit, count in counts.items()]


def native_lfl(body: object, country: str, period: Window, granularity: str,
               expected: list[str], *, by_country: bool = False) -> list[NativeLfl]:
    """Raw LFL, без ×100, свёртки buckets или предположения о базовом периоде."""
    if by_country:
        if not isinstance(country, str) or not re.fullmatch(r"[A-Za-z]{2}", country):
            raise ShapeError("invalid country")
        country = country.upper()
        if expected != [country]:
            raise ShapeError("country LFL requires exact expected country")
        subjects = set(expected)
    else:
        country, units = _context(country, "UTC", expected)
        subjects = set(units)
    if granularity not in {"Day", "Week", "Month"}:
        raise ShapeError("invalid granularity")
    result, seen = [], set()
    for row in _rows(body, "lfl"):
        raw_country = row.get("countryId")
        if not isinstance(raw_country, str) or raw_country.upper() != country:
            raise ShapeError("unexpected countryId")
        subject = country if by_country else _unit(row.get("unitId"))
        if by_country and "unitId" in row:
            raise ShapeError("unexpected unitId in country LFL")
        try:
            raw_date = row.get("date")
            if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
                raise ValueError
            bucket = date.fromisoformat(raw_date)
        except ValueError:
            raise ShapeError("invalid LFL date") from None
        if subject not in subjects or (subject, bucket) in seen:
            raise ShapeError("unexpected or duplicate LFL bucket")
        seen.add((subject, bucket))
        raw: list[Decimal | None] = []
        for field in ("lflRevenue", "lflOrder"):
            if field not in row:
                raise ShapeError("missing " + field)
            raw.append(None if row[field] is None else _number(row[field], field))
        result.append(NativeLfl(country, subject, period, granularity, bucket, raw[0], raw[1]))
    return result
