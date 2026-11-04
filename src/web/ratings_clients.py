"""Клиентские оценки из существующих месячных агрегатов Dodo IS."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.db import customer_ratings as read
from src.db.errors import RatingsError
from src.domain.dodois_metrics import next_month
from src.ratings import clients, freshness

from . import ratings_words
from .texts import t

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class View:
    total: clients.Line
    units: tuple[clients.Line, ...]
    begin: date
    end: date
    months: tuple[date, ...] = ()
    latest: date | None = None
    loaded: datetime | None = None
    status: str | None = None
    failed: bool = False
    incomplete: bool = False
    partial_period: bool = False


def load(codes: tuple[str, ...], begin: date, end: date, *, today: date) -> View:
    start, stop = clients.coverage(begin, end, today)
    empty = clients.aggregate("", "", "", [])
    if not codes:
        return View(empty, (), start, stop)
    try:
        rows = read.monthly(codes, start, stop)
    except RatingsError:
        log.warning("Клиентские оценки не прочитались", exc_info=True)
        return View(empty, (), start, stop, status="stale", failed=True)
    metadata_failed = False
    try:
        states = {s.country: s for s in read.loads(codes)}
    except RatingsError:
        log.warning("Журнал клиентских оценок не прочитался", exc_info=True)
        states = {}
        metadata_failed = True
    try:
        latest = read.latest_month(codes)
    except RatingsError:
        log.warning("Последний месяц клиентских оценок не прочитался", exc_info=True)
        latest = None
        metadata_failed = True
    complete = all(c in states and states[c].last_ok is not None for c in codes)
    loaded = min(s.last_ok for s in states.values() if s.last_ok is not None) if complete else None
    if loaded is not None:
        loaded = loaded.astimezone(freshness.local_zone())
    failed = metadata_failed or any(s.failed for s in states.values())
    status = None
    if failed:
        status = "stale"
    elif complete and loaded is not None:
        status = freshness.classify_age(loaded, today).value
    months = tuple(sorted({r.month for r in rows}))
    end_of_coverage = min(next_month(stop) - timedelta(days=1), today - timedelta(days=1))
    return View(
        total=clients.aggregate("", "", "", rows),
        units=clients.units(rows),
        begin=months[0] if months else start,
        end=(
            min(next_month(months[-1]) - timedelta(days=1), today - timedelta(days=1))
            if months
            else end_of_coverage
        ),
        months=months,
        latest=latest,
        loaded=loaded,
        status=status,
        failed=failed,
        incomplete=not complete,
        partial_period=start != begin or end_of_coverage != min(end, today),
    )


_AT = "%d.%m.%Y %H:%M"


def help_rows(view: View, lang: str) -> tuple[str, ...]:
    """Строки под «?» у раздела: за какие месяцы учтено, как считаются месяцы, когда загружено."""
    rows: list[str] = []
    if view.months:
        rows.append(
            t(
                "ratings.clients.coverage",
                lang,
                months=ratings_words.months_phrase(view.months, lang),
                end=view.end.strftime("%d.%m.%Y"),
            )
        )
    rows.append(t("ratings.clients.monthsOnly", lang))
    if view.loaded:
        rows.append(t("ratings.clients.loaded", lang, at=view.loaded.strftime(_AT)))
    return tuple(rows)
