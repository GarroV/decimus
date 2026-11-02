"""Динамика проверок по датам; количество отдельно по годам или месяцам."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from src.db import inspection_timeline as store
from src.db.errors import DbError
from src.db.reach import Reach

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Bucket:
    """Период с сохранённой оценкой и координатами двух независимых шкал."""

    label: str
    count: int
    average: float | None
    count_height: float


@dataclass(frozen=True)
class Point:
    """Наблюдаемая дата: сохранённые оценки, без выдуманных промежуточных измерений."""

    day: date
    count: int
    average: float
    x: float
    y: float


@dataclass(frozen=True)
class Tick:
    day: date
    x: float


@dataclass(frozen=True)
class Timeline:
    """Данные двух представлений одной истории, включая пустые периоды."""

    grain: str = "year"
    year: int = 0
    years: tuple[int, ...] = ()
    buckets: tuple[Bucket, ...] = ()
    count: int = 0
    average: float | None = None
    failed: bool = False
    points: tuple[Point, ...] = ()
    ticks: tuple[Tick, ...] = ()


def build(
    rows: tuple[store.Month | store.Day, ...], args: Mapping[str, str], *, today: date
) -> Timeline:
    """Средняя взвешена числом проверок; пустой месяц не становится нулевой оценкой."""
    years = tuple(range(min(r.start.year for r in rows), today.year + 1)) if rows else ()
    grain = "month" if args.get("history_grain") == "month" else "year"
    raw = args.get("history_year", "")
    wanted = int(raw) if raw.isascii() and raw.isdigit() and len(raw) == 4 else today.year
    year = wanted if wanted in years else (years[-1] if years else today.year)
    keys = tuple(range(1, 13)) if grain == "month" else years
    totals: dict[int, tuple[int, float]] = dict.fromkeys(keys, (0, 0.0))
    for row in rows:
        if grain == "month" and row.start.year != year:
            continue
        key = row.start.month if grain == "month" else row.start.year
        n, total = totals[key]
        totals[key] = (n + row.count, total + row.total)
    maximum = max((n for n, _ in totals.values()), default=1) or 1
    buckets = tuple(
        Bucket(
            f"{key:02}" if grain == "month" else str(key),
            n,
            round(total / n, 1) if n else None,
            80 * n / maximum,
        )
        for key, (n, total) in totals.items()
    )
    count = sum(n for n, _ in totals.values())
    total = sum(s for _, s in totals.values())
    selected = tuple(r for r in rows if grain != "month" or r.start.year == year)
    points, ticks = _plot(selected)
    return Timeline(
        grain,
        year,
        years,
        buckets,
        count,
        round(total / count, 1) if count else None,
        points=points,
        ticks=ticks,
    )


def _plot(
    rows: tuple[store.Month | store.Day, ...],
) -> tuple[tuple[Point, ...], tuple[Tick, ...]]:
    """Общая шкала 0–100 и непрерывная шкала дат; повторные даты объединяются."""
    daily: dict[date, tuple[int, float]] = {}
    for row in rows:
        n, total = daily.get(row.start, (0, 0.0))
        daily[row.start] = (n + row.count, total + row.total)
    observed = sorted(day for day, (n, _) in daily.items() if n)
    if not observed:
        return (), ()
    first, last = observed[0], observed[-1]
    span = (last - first).days

    def x(day: date) -> float:
        return 0.5 if not span else (day - first).days / span

    points = tuple(
        Point(
            day,
            daily[day][0],
            round(daily[day][1] / daily[day][0], 1),
            x(day),
            248 - 2 * daily[day][1] / daily[day][0],
        )
        for day in observed
    )
    dates = (
        (first,)
        if not span
        else tuple(dict.fromkeys(first + timedelta(days=round(span * i / 4)) for i in range(5)))
    )
    return points, tuple(Tick(day, x(day)) for day in dates)


def load(
    *, reach: Reach, countries: tuple[str, ...], args: Mapping[str, str], today: date
) -> Timeline:
    """Отказ чтения явно отличается от отсутствия проверок."""
    try:
        return build(store.days(reach=reach, countries=countries, today=today), args, today=today)
    except DbError:
        log.warning("История проверок не прочиталась", exc_info=True)
        return Timeline(failed=True)
