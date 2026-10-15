"""Сетка месяца на экране «Календарь» (D497): проверки по дням.

Список «Где нужно проверить» с экрана снят (владелец 14.10.2026: «не ясно зачем
он нужен там. пока скрой вообще список»). Экран показывает календарь: неделя
— строка с понедельника, в клетке дня — проверки с этой датой обхода. На этой
же сетке потом встанут поездки сотрудников УК.

Ни одного обращения к базе: строки приходят готовыми, здесь только раскладка.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from src.db.models import InspectionRow

#: Сколько месяцев рисовать за раз: период «с — по» бывает любым, а сетка на
#: год — это уже не календарь, а простыня.
MAX_MONTHS = 3
#: Сколько проверок печатать в клетке дня; остальные — «ещё N».
DAY_ROWS = 3
DAYS_IN_WEEK = 7


@dataclass(frozen=True)
class Day:
    day: date
    in_month: bool
    today: bool
    rows: tuple[InspectionRow, ...]

    @property
    def shown(self) -> tuple[InspectionRow, ...]:
        return self.rows[:DAY_ROWS]

    @property
    def more(self) -> int:
        return max(len(self.rows) - DAY_ROWS, 0)


@dataclass(frozen=True)
class Month:
    first: date
    weeks: tuple[tuple[Day, ...], ...]
    total: int


def _first_of(day: date) -> date:
    return day.replace(day=1)


def _next_month(first: date) -> date:
    return (first + timedelta(days=32)).replace(day=1)


def month_end(first: date) -> date:
    """Последний день месяца, начатого `first`."""
    return _next_month(first) - timedelta(days=1)


def months_between(start: date | None, end: date | None, today: date) -> tuple[date, ...]:
    """Первые числа месяцев периода, не больше `MAX_MONTHS`; без границ — текущий месяц."""
    if start is None or end is None:
        return (_first_of(today),)
    первые: list[date] = []
    месяц = _first_of(start)
    while месяц <= end and len(первые) < MAX_MONTHS:
        первые.append(месяц)
        месяц = _next_month(месяц)
    return tuple(первые) or (_first_of(today),)


def month_grid(first: date, rows: Iterable[InspectionRow], today: date) -> Month:
    """Сетка месяца `first`: полные недели с понедельника, проверки по дате обхода."""
    по_дням: dict[date, list[InspectionRow]] = {}
    for row in rows:
        по_дням.setdefault(row.inspection_date, []).append(row)
    следующий = _next_month(first)
    начало = first - timedelta(days=first.weekday())
    недели: list[tuple[Day, ...]] = []
    день = начало
    while день < следующий:
        неделя = tuple(
            Day(
                day=день + timedelta(days=i),
                in_month=first <= день + timedelta(days=i) < следующий,
                today=день + timedelta(days=i) == today,
                rows=tuple(
                    sorted(по_дням.get(день + timedelta(days=i), ()), key=lambda r: r.unit_name)
                ),
            )
            for i in range(DAYS_IN_WEEK)
        )
        недели.append(неделя)
        день += timedelta(days=DAYS_IN_WEEK)
    всего = sum(len(v) for k, v in по_дням.items() if first <= k < следующий)
    return Month(first=first, weeks=tuple(недели), total=всего)
