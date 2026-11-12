"""D746: actual source windows, with the same per-unit fallback as Quality.

Cards never turn synthetic half-month sheet dates into Dodo IS dates. The
aggregate facts may use the existing sheet score for a unit with no API score;
provenance explicitly distinguishes that fallback from real period cards.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.db import ratings_read as read
from src.domain.dodois_metrics import first_of_month, next_month, rating_months

from .model import RKO, RS
from .periods import KIND_RANGE, KIND_RATING, ReportPeriod
from .summary import Fact, group_average, unit_counts

PREVIOUS_LOOKBACK_DAYS = 366


@dataclass(frozen=True)
class PeriodTile:
    period_id: int | None
    rating_type: str
    key: str
    begin_on: date
    end_on: date
    title_ru: str
    title_en: str
    state: str
    avg: float | None
    units: int
    checkups: int | None
    publication_statuses: tuple[str, ...] = ()
    source: str = "dodois"
    actual_dates: bool = True

    @property
    def months(self) -> tuple[date, ...]:
        """RS has one owning month; an RKO week can appear in both month groups."""
        return tuple(rating_months(self.rating_type, self.begin_on, self.end_on))


@dataclass(frozen=True)
class PeriodView:
    tiles: tuple[PeriodTile, ...]
    facts: tuple[Fact, ...]
    source: str
    actual_dates: bool


def _months(period: ReportPeriod) -> tuple[date, ...] | None:
    """Whole-month frames use the already accepted RS/RKO month ownership."""
    if (
        period.begin.day != 1
        or period.end.day != calendar.monthrange(period.end.year, period.end.month)[1]
    ):
        return None
    month, last = first_of_month(period.begin), first_of_month(period.end)
    result = [month]
    while month < last:
        month = next_month(month)
        result.append(month)
    return tuple(result)


def _selected(row: read.SourceRatingPeriod, period: ReportPeriod) -> bool:
    months = _months(period)
    if months is not None:
        return bool(set(rating_months(row.rating_type, row.begin_on, row.end_on)) & set(months))
    return row.end_on >= period.begin and row.begin_on <= period.end


def _source_fact(row: read.SourceRatingPeriod) -> Fact:
    # Internal grouping identity only: negative ids cannot collide with the
    # positive database period ids used by sheet fallback. Links use the actual
    # date-range key, never this number (the metrics API has no period id).
    identity = -((row.begin_on.toordinal() * 3_660_000 + row.end_on.toordinal()) * 2)
    if row.rating_type == RKO:
        identity -= 1
    return Fact(
        row.unit,
        row.unit_name,
        row.country,
        row.rating_type,
        identity,
        row.begin_on,
        row.score,
        row.end_on,
    )


def load(kind: str, countries: Sequence[str], period: ReportPeriod, today: date) -> PeriodView:
    """Actual period cards and aggregate facts; unknown dates stay unknown.

    A unit with selected API windows uses those windows; another unit falls
    back to its already stored ratings facts, as on Quality. Cards themselves
    contain only actual API dates and their API scores. Future windows can be
    shown, but their score does not enter current results before they start.
    """
    if kind not in (RS, RKO):
        raise ValueError("Unknown rating source")
    codes = tuple(dict.fromkeys(countries))
    if not codes:
        return PeriodView((), (), "", False)
    rows = tuple(
        row
        for row in read.source_rating_periods(
            countries=codes, rating_type=kind, begin=period.begin, end=period.end
        )
        if row.rating_type == kind and row.country in codes and _selected(row, period)
    )
    current = tuple(row for row in rows if row.begin_on <= today)
    api_units = {row.unit for row in current}
    api_facts = tuple(_source_fact(row) for row in current)
    legacy = (
        tuple(
            Fact(*row)
            for row in read.score_facts(
                countries=codes, begin=period.begin, end=min(period.end, today)
            )
            if row[3] == kind and row[0] not in api_units and row[2] in codes and row[5] <= today
        )
        if period.begin <= today
        else ()
    )
    tiles = []
    windows = sorted({(row.begin_on, row.end_on) for row in rows})
    for begin, end in windows:
        window = tuple(row for row in rows if (row.begin_on, row.end_on) == (begin, end))
        facts = tuple(_source_fact(row) for row in window if begin <= today)
        known_checks = [row.checkups for row in window if row.checkups is not None]
        title = f"{begin:%d.%m.%Y} — {end:%d.%m.%Y}"
        tiles.append(
            PeriodTile(
                period_id=None,
                rating_type=kind,
                key=f"{begin.isoformat()}..{end.isoformat()}",
                begin_on=begin,
                end_on=end,
                title_ru=title,
                title_en=title,
                state="upcoming" if begin > today else "closed" if end < today else "current",
                avg=group_average(facts, kind, codes),
                units=sum(unit_counts(facts, kind).values()),
                checkups=sum(known_checks) if known_checks and begin <= today else None,
                publication_statuses=tuple(
                    sorted({row.publish_status for row in window if row.publish_status is not None})
                ),
            )
        )
    source = "mixed" if rows and legacy else "dodois" if rows else "sheet" if legacy else ""
    return PeriodView(tuple(tiles), api_facts + legacy, source, bool(rows) and not legacy)


def build(
    kind: str, countries: Sequence[str], period: ReportPeriod, today: date
) -> tuple[PeriodTile, ...]:
    """Period-card-only convenience API; `load` also exposes aggregate provenance."""
    return load(kind, countries, period, today).tiles


def previous_for(
    kind: str, countries: Sequence[str], period: ReportPeriod, today: date
) -> ReportPeriod | None:
    """Previous available actual API window, never a same-length shifted range.

    Provenance is strictly Dodo IS metrics. Every currently participating unit
    must have the exact selected window and the same immediate predecessor.
    Conflicting cadences, missing history or legacy-only fallback make the delta
    unknown. Month/quarter/year navigation remains the caller's calendar concern.
    """
    if kind not in (RS, RKO):
        raise ValueError("Unknown rating source")
    codes = tuple(dict.fromkeys(countries))
    calendar_year = period.begin == date(period.begin.year, 1, 1) and period.end == date(
        period.begin.year, 12, 31
    )
    if (
        not codes
        or period.kind not in (KIND_RANGE, KIND_RATING)
        or calendar_year
        or period.begin > today
    ):
        return None
    lookback = date.fromordinal(max(1, period.begin.toordinal() - PREVIOUS_LOOKBACK_DAYS))
    until = min(period.end, today)
    rows = tuple(
        row
        for row in read.source_rating_periods(
            countries=codes, rating_type=kind, begin=lookback, end=until
        )
        if row.rating_type == kind and row.country in codes and lookback <= row.begin_on <= until
    )
    current = tuple(row for row in rows if row.end_on >= period.begin)
    if not current or any(
        (row.begin_on, row.end_on) != (period.begin, period.end) for row in current
    ):
        return None
    units = {row.unit for row in current}
    predecessors = set()
    for unit in units:
        earlier = [row for row in rows if row.unit == unit and row.begin_on < period.begin]
        if not earlier:
            return None
        previous = max(earlier, key=lambda row: row.begin_on)
        if previous.end_on >= period.begin:
            return None
        predecessors.add((previous.begin_on, previous.end_on))
    if len(predecessors) != 1:
        return None
    begin, end = predecessors.pop()
    previous_rows = tuple(row for row in rows if row.begin_on <= end and row.end_on >= begin)
    if any((row.begin_on, row.end_on) != (begin, end) for row in previous_rows):
        return None
    previous_units = {row.unit for row in previous_rows}
    legacy = (
        Fact(*row)
        for row in read.score_facts(countries=codes, begin=lookback, end=until)
        if row[3] == kind and row[2] in codes and row[5] <= until
    )
    for fact in legacy:
        fact_end = fact.end_on or fact.begin_on
        if fact.begin_on <= until and fact_end >= period.begin and fact.unit not in units:
            return None
        if fact.begin_on <= end and fact_end >= begin and fact.unit not in previous_units:
            return None
    return ReportPeriod(KIND_RANGE, f"{begin.isoformat()}..{end.isoformat()}", begin, end)
