"""Разделы «Агрегаторы» и «Карты» (D660): охват пиццерий площадками.

Читает реестр пиццерий, привязанные точки и оценки; расчётов оценки здесь нет —
группы считает `ratings.aggregators.summary`, ячейки пиццерий — `ratings.coverage`.
Здесь только сборка для экрана: плитки по площадкам, «страна × площадка» с
раскрытием пиццерий и «чего не хватает» с причиной словами у каждой пиццерии.
База не ответила — `None` и след в журнале: раздел скажет об этом, страница живёт.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.db import agg_store, maps_store
from src.db.errors import RatingsError
from src.ratings import coverage, pointer
from src.ratings.aggregators import collect
from src.ratings.aggregators import summary as ragg

logger = logging.getLogger(__name__)

#: Причины, по которым у пиццерии нет точки или оценки на площадке.
UNLINKED = "unlinked"
PAUSED = "paused"
UNRATED = "unrated"
STALE = "stale"


@dataclass(frozen=True)
class Reason:
    platform: str
    code: str
    on_date: date | None = None


@dataclass(frozen=True)
class Gap:
    unit: agg_store.UnitRow
    reasons: tuple[Reason, ...]


@dataclass(frozen=True)
class Tile:
    platform: str
    score: ragg.AggScore | None
    linked: int  # пиццерий с точкой на площадке
    expected: int  # пиццерий, где площадка в стране работает


@dataclass(frozen=True)
class CountryBlock:
    code: str
    scores: dict[str, ragg.AggScore]
    units: tuple[coverage.Row, ...]


@dataclass(frozen=True)
class AggView:
    platforms: tuple[str, ...]
    tiles: tuple[Tile, ...]
    countries: tuple[CountryBlock, ...]
    gaps: tuple[Gap, ...]
    as_of: date | None
    later: bool  # оценки взяты позже конца периода


def agg_countries() -> dict[str, frozenset[str]]:
    """Где агрегатор ожидается: поисковый — в странах сборщика, известной точки
    (Glovo, Chowdeck) — там, где у него есть точки; на паузе — только где точки
    остались (D397)."""
    expected = {m.KEY: frozenset(m.COUNTRIES) for m in collect.SEARCHERS}
    for module in collect.KNOWN + collect.PAUSED:
        has = agg_store.point_countries(module.KEY)
        expected[module.KEY] = has if module in collect.KNOWN else has & frozenset(module.COUNTRIES)
    return expected


def _gaps(rows: Sequence[coverage.Row], platforms: Sequence[str]) -> tuple[Gap, ...]:
    paused = {m.KEY for m in collect.PAUSED}
    gaps = []
    for row in rows:
        reasons = []
        for key in platforms:
            cell = row.cells[key]
            if cell.state == coverage.MISSING:
                reasons.append(Reason(key, PAUSED if key in paused else UNLINKED))
            elif cell.state == coverage.UNRATED:
                reasons.append(Reason(key, UNRATED))
            elif cell.state == coverage.SCORE and cell.stale:
                reasons.append(Reason(key, STALE, cell.on_date))
        if reasons:
            gaps.append(Gap(row.unit, tuple(reasons)))
    return tuple(gaps)


def _tile(key: str, rows: Sequence[coverage.Row], overall: ragg.GroupAggs) -> Tile:
    states = [r.cells[key].state for r in rows]
    return Tile(
        key,
        overall.scores.get(key),
        sum(s in (coverage.SCORE, coverage.UNRATED) for s in states),
        sum(s != coverage.ABSENT for s in states),
    )


def build_agg(codes: Sequence[str], *, until: date, today: date) -> AggView | None:
    """Раздел «Агрегаторы» по странам выбранного среза; `None` — база не ответила."""
    try:
        units = agg_store.units(tuple(codes))
        cov = coverage.build(units, (), agg_store.coverage(), agg_countries(), today)
        groups = [(c, (c,)) for c in codes] + [("", tuple(codes))]
        _, found, later = ragg.for_groups(groups, until=until, today=today)
    except RatingsError:
        logger.warning("Охват агрегаторов не прочитался", exc_info=True)
        return None
    platforms = tuple(p.key for p in cov.platforms)
    *by_country, overall = found
    countries = tuple(
        CountryBlock(g.group, g.scores, tuple(r for r in cov.rows if r.unit.country == g.group))
        for g in by_country
    )
    dates = [g.as_of for g in found if g.as_of]
    return AggView(
        platforms,
        tuple(_tile(p, cov.rows, overall) for p in platforms),
        countries,
        _gaps(cov.rows, platforms),
        max(dates) if dates else None,
        later,
    )


def build_maps(codes: Sequence[str], *, today: date) -> coverage.Coverage | None:
    """Пиццерии стран среза на картах Google и Яндекса; `None` — база не ответила."""
    try:
        units = agg_store.units(tuple(codes))
        maps = [
            (str(p), maps_store.unit_latest(p))
            for p in (pointer.GOOGLE, pointer.YANDEX)  # порядок колонок: Google, Яндекс
        ]
        return coverage.build(units, maps, (), {}, today)
    except RatingsError:
        logger.warning("Охват карт не прочитался", exc_info=True)
        return None
