"""Общая история проверок для страны и рейтингов: годы либо месяцы одного года."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

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
    x: float
    count_height: float
    score_y: float | None


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


def build(rows: tuple[store.Month, ...], args: Mapping[str, str], *, today: date) -> Timeline:
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
            45 + i * 550 / max(len(keys) - 1, 1),
            80 * n / maximum,
            230 - 0.8 * total / n if n else None,
        )
        for i, (key, (n, total)) in enumerate(totals.items())
    )
    count = sum(n for n, _ in totals.values())
    total = sum(s for _, s in totals.values())
    return Timeline(grain, year, years, buckets, count, round(total / count, 1) if count else None)


def load(
    *, reach: Reach, countries: tuple[str, ...], args: Mapping[str, str], today: date
) -> Timeline:
    """Отказ чтения явно отличается от отсутствия проверок."""
    try:
        return build(store.months(reach=reach, countries=countries, today=today), args, today=today)
    except DbError:
        log.warning("История проверок не прочиталась", exc_info=True)
        return Timeline(failed=True)
