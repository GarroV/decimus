"""Сводка клиентских оценок: только целые месячные агрегаты, вес — число оценок."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from src.db.customer_ratings import MonthlyKr
from src.domain.dodois_metrics import first_of_month, next_month


@dataclass(frozen=True)
class Score:
    average: Decimal | None
    count: int


@dataclass(frozen=True)
class Line:
    key: str
    name: str
    country: str
    dine: Score
    delivery: Score
    total: Score


def weighted(parts: Sequence[tuple[Decimal | None, int]]) -> Score:
    count = sum(n for _, n in parts)
    # Не теряем число оценок, когда источник не сообщил среднее для части из них.
    if not count or any(avg is None and n > 0 for avg, n in parts):
        return Score(None, count)
    return Score(sum((avg * n for avg, n in parts if avg is not None), Decimal(0)) / count, count)


def aggregate(key: str, name: str, country: str, rows: Sequence[MonthlyKr]) -> Line:
    dine = [(r.dine_avg, r.dine_count) for r in rows]
    delivery = [(r.delivery_avg, r.delivery_count) for r in rows]
    return Line(key, name, country, weighted(dine), weighted(delivery), weighted(dine + delivery))


def units(rows: Sequence[MonthlyKr]) -> tuple[Line, ...]:
    grouped: dict[str, list[MonthlyKr]] = defaultdict(list)
    for row in rows:
        grouped[row.unit].append(row)
    return tuple(
        aggregate(key, group[0].name, group[0].country, group)
        for key, group in sorted(
            grouped.items(), key=lambda item: (item[1][0].country, item[1][0].name)
        )
    )


def coverage(begin: date, end: date, today: date) -> tuple[date, date]:
    """Только месяцы внутри отбора; текущий допустим с первого числа до сегодняшней даты.

    Агрегаты не позволяют разрезать месяц на дни. Произвольные неполные границы не
    расширяем молча до соседних дат и не делим оценки пропорционально дням.
    """
    start = first_of_month(begin)
    if begin != start:
        start = next_month(start)
    stop = first_of_month(end)
    if end < next_month(stop) - timedelta(days=1):
        if stop != first_of_month(today) or end < today:
            stop = first_of_month(stop - timedelta(days=1))
    return start, stop
