"""Период отчёта: месяц, квартал или период рейтинга РС (спека «Словарь», решение плана 12).

Оценка за месяц или квартал — среднее за периоды рейтинга, начавшиеся внутри
(`summary`). Ключ периода живёт в адресе страницы: `2026-09`, `2026-Q3`, `rs:<id>`.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

KIND_MONTH = "month"
KIND_QUARTER = "quarter"
KIND_RATING = "rating"
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_QUARTER = re.compile(r"^(\d{4})-Q([1-4])$")
_RATING = re.compile(r"^rs:(\d+)$")


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


def parse_period(key: str, *, rs_periods: Sequence[RatingPeriod]) -> ReportPeriod | None:
    if found := _MONTH.match(key):
        month = int(found[2])
        return month_period(int(found[1]), month) if 1 <= month <= 12 else None
    if found := _QUARTER.match(key):
        return quarter_period(int(found[1]), int(found[2]))
    if found := _RATING.match(key):
        wanted = int(found[1])
        return next((_rating(p) for p in rs_periods if p.id == wanted), None)
    return None


def previous_period(
    period: ReportPeriod, *, rs_periods: Sequence[RatingPeriod]
) -> ReportPeriod | None:
    if period.kind == KIND_MONTH:
        year, month = period.begin.year, period.begin.month
        return month_period(year - 1, 12) if month == 1 else month_period(year, month - 1)
    if period.kind == KIND_QUARTER:
        year, quarter = period.begin.year, (period.begin.month - 1) // 3 + 1
        return quarter_period(year - 1, 4) if quarter == 1 else quarter_period(year, quarter - 1)
    earlier = [p for p in rs_periods if p.begin_on < period.begin]
    return _rating(max(earlier, key=lambda p: p.begin_on)) if earlier else None


def default_period(latest: date | None, *, today: date) -> ReportPeriod:
    anchor = latest or today
    return quarter_period(anchor.year, (anchor.month - 1) // 3 + 1)
