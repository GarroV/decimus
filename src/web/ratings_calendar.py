"""Календарь периода раздела «Рейтинги» (D357): стрелки ← → и сетка по годам.

Стрелка листает на длину выбранного периода — месяц, квартал или период РС —
и ведёт только туда, где есть данные. Сетка: по строке на год, в ней четыре
квартала и двенадцать месяцев; ниже — периоды РС. Ячейка без данных видна, но
не ссылка. Ни одного вычисления оценок — только ключи периодов (`periods`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.ratings import periods as rp

from .texts import t


@dataclass(frozen=True)
class Cell:
    key: str
    label: str
    has_data: bool
    is_current: bool


@dataclass(frozen=True)
class Year:
    year: int
    quarters: tuple[Cell, ...]
    months: tuple[Cell, ...]


@dataclass(frozen=True)
class Calendar:
    title: str
    prev: str | None
    next: str | None
    years: tuple[Year, ...]
    rating: tuple[Cell, ...]


def _rs_title(p: rp.RatingPeriod, lang: str) -> str:
    return p.title_ru if lang == "ru" else p.title_en


def _title(period: rp.ReportPeriod, rs: tuple[rp.RatingPeriod, ...], lang: str) -> str:
    if period.kind == rp.KIND_MONTH:
        return f"{t(f'ratings.month.{period.begin.month}', lang)} {period.begin.year}"
    if period.kind == rp.KIND_QUARTER:
        return f"{period.begin.year} Q{(period.begin.month - 1) // 3 + 1}"
    found = next((p for p in rs if f"rs:{p.id}" == period.key), None)
    return _rs_title(found, lang) if found else period.key


def _year(year: int, months: set[tuple[int, int]], selected: str, lang: str) -> Year:
    quarters = tuple(
        Cell(
            rp.quarter_period(year, q).key,
            f"Q{q}",
            any((year, m) in months for m in range(3 * q - 2, 3 * q + 1)),
            rp.quarter_period(year, q).key == selected,
        )
        for q in range(1, 5)
    )
    month_cells = tuple(
        Cell(
            rp.month_period(year, m).key,
            t(f"ratings.month.{m}", lang),
            (year, m) in months,
            rp.month_period(year, m).key == selected,
        )
        for m in range(1, 13)
    )
    return Year(year, quarters, month_cells)


def build(
    selected: rp.ReportPeriod,
    data_months: tuple[date, ...],
    rs_periods: tuple[rp.RatingPeriod, ...],
    lang: str,
) -> Calendar:
    months = {(m.year, m.month) for m in data_months}
    years = sorted({y for y, _ in months} | {selected.begin.year}, reverse=True)
    grid = tuple(_year(y, months, selected.key, lang) for y in years)
    rating = tuple(
        Cell(f"rs:{p.id}", _rs_title(p, lang), True, f"rs:{p.id}" == selected.key)
        for p in sorted(rs_periods, key=lambda p: p.begin_on, reverse=True)
    )
    known = {c.key for y in grid for c in (*y.quarters, *y.months) if c.has_data}
    known |= {c.key for c in rating}

    def reachable(period: rp.ReportPeriod | None) -> str | None:
        return period.key if period is not None and period.key in known else None

    return Calendar(
        title=_title(selected, rs_periods, lang),
        prev=reachable(rp.previous_period(selected, rs_periods=rs_periods)),
        next=reachable(rp.next_period(selected, rs_periods=rs_periods)),
        years=grid,
        rating=rating,
    )
