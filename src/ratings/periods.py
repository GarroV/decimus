"""Период отчёта: месяц, квартал, период рейтинга РС (спека «Словарь», решение плана 12)
или произвольный отрезок «с — по» из календаря.

Оценка за период — среднее за периоды рейтинга, начавшиеся внутри (`summary`).
Ключ периода живёт в адресе страницы: `2026-09`, `2026-Q3`, `rs:<id>`,
`2026-07-05..2026-08-20`.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

KIND_MONTH = "month"
KIND_QUARTER = "quarter"
KIND_RATING = "rating"
KIND_RANGE = "range"
_MONTH = re.compile(r"(\d{4})-(\d{2})", re.ASCII)
_QUARTER = re.compile(r"(\d{4})-Q([1-4])", re.ASCII)
_MIN_YEAR = 1  # date() не знает года 0
_RATING = re.compile(r"rs:(\d+)", re.ASCII)


@dataclass(frozen=True)
class ReportPeriod:
    kind: str
    key: str
    begin: date
    end: date


@dataclass(frozen=True)
class RatingPeriod:
    id: int
    begin_on: date
    end_on: date
    title_ru: str
    title_en: str


def month_period(year: int, month: int) -> ReportPeriod:
    last = calendar.monthrange(year, month)[1]
    return ReportPeriod(
        KIND_MONTH, f"{year}-{month:02d}", date(year, month, 1), date(year, month, last)
    )


def quarter_period(year: int, quarter: int) -> ReportPeriod:
    first = 3 * (quarter - 1) + 1
    last = calendar.monthrange(year, first + 2)[1]
    return ReportPeriod(
        KIND_QUARTER, f"{year}-Q{quarter}", date(year, first, 1), date(year, first + 2, last)
    )


def _rating(period: RatingPeriod) -> ReportPeriod:
    return ReportPeriod(KIND_RATING, f"rs:{period.id}", period.begin_on, period.end_on)


def range_period(begin: date, end: date, *, rs_periods: Sequence[RatingPeriod]) -> ReportPeriod:
    """Отрезок «с — по» из календаря. Совпал с целым месяцем, кварталом или
    периодом РС — это он и есть (у него «Δ к прошлому такому же» и своё имя);
    иначе — произвольный отрезок. Перепутанные границы меняются местами."""
    if begin > end:
        begin, end = end, begin
    exact = [month_period(begin.year, begin.month)]
    exact.append(quarter_period(begin.year, (begin.month - 1) // 3 + 1))
    exact += [_rating(p) for p in rs_periods]
    found = next((p for p in exact if (p.begin, p.end) == (begin, end)), None)
    return found or ReportPeriod(KIND_RANGE, f"{begin.isoformat()}..{end.isoformat()}", begin, end)


def _range(key: str, rs_periods: Sequence[RatingPeriod]) -> ReportPeriod | None:
    begin, sep, end = key.partition("..")
    if not sep:
        return None
    try:
        return range_period(
            date.fromisoformat(begin), date.fromisoformat(end), rs_periods=rs_periods
        )
    except ValueError:
        return None


def parse_period(key: str, *, rs_periods: Sequence[RatingPeriod]) -> ReportPeriod | None:
    if ".." in key:
        return _range(key, rs_periods)
    if found := _MONTH.fullmatch(key):
        year, month = int(found[1]), int(found[2])
        return month_period(year, month) if year >= _MIN_YEAR and 1 <= month <= 12 else None
    if found := _QUARTER.fullmatch(key):
        year = int(found[1])
        return quarter_period(year, int(found[2])) if year >= _MIN_YEAR else None
    if found := _RATING.fullmatch(key):
        wanted = int(found[1])
        return next((_rating(p) for p in rs_periods if p.id == wanted), None)
    return None


def _shifted(period: ReportPeriod, step: int) -> ReportPeriod | None:
    """Соседний отрезок той же длины; за краем календаря — `None`."""
    span = timedelta(days=(period.end - period.begin).days + 1)
    try:
        begin, end = period.begin + span * step, period.end + span * step
    except OverflowError:
        return None
    return ReportPeriod(KIND_RANGE, f"{begin.isoformat()}..{end.isoformat()}", begin, end)


def previous_period(
    period: ReportPeriod, *, rs_periods: Sequence[RatingPeriod]
) -> ReportPeriod | None:
    if period.kind == KIND_MONTH:
        year, month = period.begin.year, period.begin.month
        if year == _MIN_YEAR and month == 1:
            return None
        return month_period(year - 1, 12) if month == 1 else month_period(year, month - 1)
    if period.kind == KIND_QUARTER:
        year, quarter = period.begin.year, (period.begin.month - 1) // 3 + 1
        if year == _MIN_YEAR and quarter == 1:
            return None
        return quarter_period(year - 1, 4) if quarter == 1 else quarter_period(year, quarter - 1)
    if period.kind == KIND_RANGE:
        return _shifted(period, -1)
    earlier = [p for p in rs_periods if p.begin_on < period.begin]
    return _rating(max(earlier, key=lambda p: p.begin_on)) if earlier else None


def next_period(period: ReportPeriod, *, rs_periods: Sequence[RatingPeriod]) -> ReportPeriod | None:
    """Следующий такой же период — для стрелки → календаря (D357)."""
    if period.kind == KIND_MONTH:
        year, month = period.begin.year, period.begin.month
        return month_period(year + 1, 1) if month == 12 else month_period(year, month + 1)
    if period.kind == KIND_QUARTER:
        year, quarter = period.begin.year, (period.begin.month - 1) // 3 + 1
        return quarter_period(year + 1, 1) if quarter == 4 else quarter_period(year, quarter + 1)
    if period.kind == KIND_RANGE:
        return _shifted(period, 1)
    later = [p for p in rs_periods if p.begin_on > period.begin]
    return _rating(min(later, key=lambda p: p.begin_on)) if later else None


def default_period(latest: date | None, *, today: date) -> ReportPeriod:
    anchor = latest or today
    return quarter_period(anchor.year, (anchor.month - 1) // 3 + 1)
