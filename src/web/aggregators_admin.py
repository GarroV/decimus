"""Административный охват агрегаторов: существующие ячейки и недельная свежесть (#1391)."""

from __future__ import annotations

import logging
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from flask import Response, abort, make_response, render_template, request

from src.db import agg_store, ratings_read
from src.db.errors import DbError
from src.ratings import coverage

from . import administration, auth, ratings_platforms

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Gap:
    """Строка «что требует внимания» или «к сведению» у площадки."""

    unit_id: str
    unit: str
    state: str  # missing | candidate | unrated | stale | not_listed
    on_date: date | None = None
    candidates: tuple[coverage.Candidate, ...] = ()
    marked: bool = False  # `not_listed` по отметке человека: можно снять


@dataclass(frozen=True)
class Pinned:
    """Закреплённая вручную привязка: можно отвязать."""

    point_key: str
    unit: str


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
    gaps: tuple[Gap, ...]
    searched: bool  # поиск у координат: «нет на площадке» следует из поиска, кнопки отметки нет
    pinned: tuple[Pinned, ...] = field(default=())

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


def _is_gap(cell: coverage.Cell) -> bool:
    return cell.state != coverage.SCORE or cell.stale


def _gap(unit: agg_store.UnitRow, cell: coverage.Cell) -> Gap:
    if cell.state == coverage.SCORE:
        return Gap(unit.dodo_id, unit.name, "stale", cell.on_date)
    if cell.state == coverage.MISSING and cell.candidates:
        return Gap(unit.dodo_id, unit.name, "candidate", None, cell.candidates)
    return Gap(unit.dodo_id, unit.name, cell.state, cell.on_date, marked=cell.marked)


def build(
    countries: Sequence[ratings_read.CountryRow],
    units: Sequence[agg_store.UnitRow],
    linked: Sequence[agg_store.CoverageRow],
    expected: Mapping[str, Collection[str]],
    loads: Sequence[agg_store.LoadState],
    unmatched: Sequence[agg_store.UnmatchedCount],
    today: date,
    hints: coverage.Hints = coverage.NO_HINTS,
    pins: Sequence[agg_store.PointLink] = (),
) -> tuple[Country, ...]:
    """Чистая сборка: данные прочитаны пачками, ни одного запроса на страну."""
    cov = coverage.build(units, (), linked, expected, today, hints=hints)
    by_load = {row.aggregator: row for row in loads}
    by_unmatched = {(row.country, row.aggregator): row for row in unmatched}
    result = []
    for country in countries:
        rows = [row for row in cov.rows if row.unit.country == country.code]
        keys = {key for key, codes in expected.items() if country.code in codes}
        keys.update(
            row.aggregator for row in unmatched if row.country == country.code and row.unmatched
        )
        in_country = {row.unit.dodo_id: row.unit.name for row in rows}
        platforms = []
        for key in sorted(keys):
            present = [
                (row.unit, row.cells[key])
                for row in rows
                if key in row.cells and row.cells[key].state != coverage.ABSENT
            ]
            # «Нет на площадке» не ожидается и не считается пробелом (D700): только сведение.
            cells = [(u, c) for u, c in present if c.state != coverage.NOT_LISTED]
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
                    tuple(_gap(u, c) for u, c in present if _is_gap(c)),
                    key in hints.searched,
                    tuple(
                        Pinned(link.point_key, in_country[link.dodo_id])
                        for link in pins
                        if link.aggregator == key and link.dodo_id in in_country
                    ),
                )
            )
        tone = "grey"
        if platforms and rows:
            # Привязана, но без оценки (мало отзывов) — норма (D700), не пробел.
            tone = "green"
            for p in platforms:
                if p.load and p.load.outcome != "ok":
                    tone = "red"
                    break
                if (
                    (p.load is not None and bool(p.load.error))
                    or not p.expected
                    or p.fresh + p.unrated != p.expected
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
        units = agg_store.units()
        hints = ratings_platforms.hints(units)
        rows = build(
            countries,
            units,
            agg_store.coverage(),
            ratings_platforms.agg_countries(),
            agg_store.load_states(),
            agg_store.unmatched_counts(),
            datetime.now(UTC).date(),
            hints,
            agg_store.point_links(),
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
            result=request.args.get("result", ""),
            split_open=selected is not None,
            split_back=administration.url("aggregators"),
            link=lambda code: administration.url("aggregators", country=code),
            settings_link=administration.url("ratings", block="aggregators"),
            **administration.nav("aggregators"),
        )
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
