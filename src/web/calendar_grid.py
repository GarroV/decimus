"""Сетка месяца для экрана «Календарь» (D477): проверки по дням.

Календарь — раздел самого календаря, где планируют командировки и поездки, а не
список «куда ехать» (тот скрыт, D477). Здесь только раскладка уже прочитанных
проверок по дням: данные те же, что у реестра «Проверки» (`inspections.load_registry`),
оценок и отбора по охвату этот модуль не знает.

Неделя — с понедельника. Период шире месяца — несколько сеток подряд; дни
месяца вне периода остаются в сетке, но без проверок и помечены (`in_period`).
В клетке видно не больше `MAX_CHIPS` проверок, остаток — числом («+N»).
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from src.db.models import InspectionRow

from .registry_period import Period

#: Сколько проверок показывать в клетке дня; остальные — числом «+N».
MAX_CHIPS = 3

#: Сколько месяцев подряд рисуется: более длинный период обрезается по этому числу,
#: иначе «с 2020 по 2026» превратился бы в стену из сеток.
MAX_MONTHS = 12


@dataclass(frozen=True)
class Chip:
    """Проверка в клетке дня."""

    id: str
    unit: str
    grade: str
    pct: float
    on_review: bool


@dataclass(frozen=True)
class Day:
    day: date
    #: День месяца этой сетки (а не хвост соседнего, дополняющий неделю).
    in_month: bool
    #: День лежит внутри выбранного периода.
    in_period: bool
    is_today: bool
    chips: tuple[Chip, ...] = ()
    #: Сколько проверок не поместилось в клетку.
    more: int = 0

    @property
    def total(self) -> int:
        return len(self.chips) + self.more


@dataclass(frozen=True)
class Month:
    first: date
    #: Недели строками, по семь дней с понедельника.
    weeks: tuple[tuple[Day, ...], ...]

    @property
    def count(self) -> int:
        return sum(day.total for week in self.weeks for day in week if day.in_month)


def clamp(period: Period) -> Period:
    """Период календаря: открытые границы не рисуются, длина — не больше `MAX_MONTHS`.

    «Всё время» и отрезок без одной границы сжимаются в то, что есть, а без дат
    вовсе — в нет-периода: экран подставит текущий месяц.
    """
    начало, конец = period.start, period.end
    if начало is None and конец is None:
        return period
    начало = начало or конец
    конец = конец or начало
    if начало is None or конец is None:
        return period
    индекс = начало.year * 12 + начало.month - 1 + MAX_MONTHS - 1
    год, номер = divmod(индекс, 12)
    предел = date(год, номер + 1, monthrange(год, номер + 1)[1])
    return Period(начало, min(конец, предел))


def _months(start: date, end: date) -> list[date]:
    текущий = start.replace(day=1)
    месяцы = []
    while текущий <= end:
        месяцы.append(текущий)
        текущий = (текущий + timedelta(days=31)).replace(day=1)
    return месяцы


def build(period: Period, rows: tuple[InspectionRow, ...], *, today: date) -> tuple[Month, ...]:
    """Месяцы периода с проверками по дням. `period` — уже без открытых границ."""
    if period.start is None or period.end is None:
        return ()
    по_дням: dict[date, list[InspectionRow]] = {}
    for row in rows:
        if period.start <= row.inspection_date <= period.end:
            по_дням.setdefault(row.inspection_date, []).append(row)
    результат = []
    for первое in _months(period.start, period.end):
        последнее = первое.replace(day=monthrange(первое.year, первое.month)[1])
        день = первое - timedelta(days=первое.weekday())
        конец_сетки = последнее + timedelta(days=6 - последнее.weekday())
        недели = []
        while день <= конец_сетки:
            неделя = []
            for _ in range(7):
                в_месяце = первое <= день <= последнее
                в_периоде = period.start <= день <= period.end
                проверки = по_дням.get(день, [])
                фишки = tuple(
                    Chip(r.id, r.unit_name, r.grade, r.pct, r.on_review)
                    for r in sorted(проверки, key=lambda r: (r.on_review, r.unit_name))
                )
                неделя.append(
                    Day(
                        day=день,
                        in_month=в_месяце,
                        in_period=в_периоде,
                        is_today=день == today,
                        chips=фишки[:MAX_CHIPS] if в_месяце else (),
                        more=max(len(фишки) - MAX_CHIPS, 0) if в_месяце else 0,
                    )
                )
                день += timedelta(days=1)
            недели.append(tuple(неделя))
        результат.append(Month(первое, tuple(недели)))
    return tuple(результат)
