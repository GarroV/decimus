"""Административный охват агрегаторов: существующие ячейки и недельная свежесть (#1391)."""

from __future__ import annotations

import logging
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from flask import Response, abort, make_response, render_template, request

from src.db import agg_store, ratings_read
from src.db.errors import DbError
from src.ratings import coverage

from . import administration, auth, ratings_platforms

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Platform:
    key: str
    expected: int
    linked: int
    scored: int
    fresh: int
    stale: int
    unrated: int
    missing: int
    unmatched: int
    excluded: int
    latest: date | None
    load: agg_store.LoadState | None
    gaps: tuple[tuple[str, str, date | None], ...]

    @property
    def error_code(self) -> str | None:
        """Только технический код: URL, заголовки и исходный текст остаются в журнале."""
        if self.load is None or not self.load.error:
            return None
        match = re.search(r"\bHTTP [1-5][0-9]{2}\b", self.load.error)
        return match.group(0) if match else "collection_error"


@dataclass(frozen=True)
class Country:
    code: str
    name_ru: str
    name_en: str
    working: int
    platforms: tuple[Platform, ...]
    tone: str


def build(
    countries: Sequence[ratings_read.CountryRow],
    units: Sequence[agg_store.UnitRow],
    linked: Sequence[agg_store.CoverageRow],
    expected: Mapping[str, Collection[str]],
    loads: Sequence[agg_store.LoadState],
    unmatched: Sequence[agg_store.UnmatchedCount],
    today: date,
) -> tuple[Country, ...]:
    """Чистая сборка: данные прочитаны пачками, ни одного запроса на страну."""
    cov = coverage.build(units, (), linked, expected, today)
    by_load = {row.aggregator: row for row in loads}
    by_unmatched = {(row.country, row.aggregator): row for row in unmatched}
    result = []
    for country in countries:
        rows = [row for row in cov.rows if row.unit.country == country.code]
        keys = {key for key, codes in expected.items() if country.code in codes}
        keys.update(
            row.aggregator for row in unmatched if row.country == country.code and row.unmatched
        )
        platforms = []
        for key in sorted(keys):
            cells = [
                (row.unit.name, row.cells[key])
                for row in rows
                if key in row.cells and row.cells[key].state != coverage.ABSENT
            ]
            scores = [cell for _, cell in cells if cell.state == coverage.SCORE]
            fresh = sum(not cell.stale for cell in scores)
            counts = by_unmatched.get((country.code, key))
            platforms.append(
                Platform(
                    key,
                    len(cells),
                    sum(cell.state in (coverage.SCORE, coverage.UNRATED) for _, cell in cells),
                    len(scores),
                    fresh,
                    len(scores) - fresh,
                    sum(cell.state == coverage.UNRATED for _, cell in cells),
                    sum(cell.state == coverage.MISSING for _, cell in cells),
                    counts.unmatched if counts else 0,
                    counts.excluded if counts else 0,
                    max((cell.on_date for cell in scores if cell.on_date), default=None),
                    by_load.get(key),
                    tuple(
                        (
                            name,
                            cell.state if cell.state != coverage.SCORE else "stale",
                            cell.on_date,
                        )
                        for name, cell in cells
                        if cell.state != coverage.SCORE or cell.stale
                    ),
                )
            )
        tone = "grey"
        if platforms and rows:
            tone = "green"
            for p in platforms:
                if p.load and p.load.outcome != "ok":
                    tone = "red"
                    break
                if (
                    (p.load is not None and bool(p.load.error))
                    or not p.expected
                    or p.fresh != p.expected
                    or p.unmatched
                    or p.load is None
                    or p.load.last_ok is None
                    or coverage.is_stale(p.load.last_ok.astimezone(UTC).date(), today)
                ):
                    tone = "yellow"
        result.append(
            Country(
                country.code, country.name_ru, country.name_en, len(rows), tuple(platforms), tone
            )
        )
    return tuple(result)


def show() -> Response:
    """Только роли управления рейтингами УК; прямой вызов защищён, как dispatch вкладки."""
    if not administration._sees_ratings(auth.current_account()):
        abort(404)
    known = True
    try:
        countries = tuple(c for c in ratings_read.countries() if c.is_imf)
        rows = build(
            countries,
            agg_store.units(),
            agg_store.coverage(),
            ratings_platforms.agg_countries(),
            agg_store.load_states(),
            agg_store.unmatched_counts(),
            datetime.now(UTC).date(),
        )
    except DbError:
        log.warning("Административный охват агрегаторов не прочитан", exc_info=True)
        rows, known = (), False
    picked = (request.args.get("country") or "").strip().upper()
    if picked and known and picked not in {row.code for row in rows}:
        abort(404)
    selected = next((row for row in rows if row.code == picked), None)
    response = make_response(
        render_template(
            "administration/aggregators.html",
            utc_stamp=lambda at: (
                at.astimezone(UTC).strftime("%d.%m.%Y %H:%M") + " UTC" if at else "—"
            ),
            rows=rows,
            known=known,
            selected=selected,
            split_open=selected is not None,
            split_back=administration.url("aggregators"),
            link=lambda code: administration.url("aggregators", country=code),
            settings_link=administration.url("ratings", block="aggregators"),
            **administration.nav("aggregators"),
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
