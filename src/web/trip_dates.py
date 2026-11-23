"""Даты новой поездки: посещения определяют период, отдельный диапазон необязателен."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from src.db.errors import TripError


def _date(raw: str | None) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TripError("trip.err.date_invalid") from exc


def creation_dates(
    start: str | None, end: str | None, visits: Sequence[Mapping[str, str]]
) -> tuple[date, date]:
    """Все указанные даты входят в поездку; одной даты достаточно даже без плана."""
    first, last = _date(start), _date(end)
    if first is not None and last is not None and last < first:
        raise TripError("trip.err.order")
    days = [day for day in (first, last) if day is not None]
    for visit in visits:
        day = _date(visit.get("day"))
        if day is None and (visit.get("unit") or visit.get("at")):
            raise TripError("trip.err.visit_day")
        if day is not None:
            days.append(day)
    if not days:
        raise TripError("trip.err.plan_dates")
    return min(days), max(days)
