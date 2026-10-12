"""Оценки пиццерий одним списком: РС, РКО, карта и агрегаторы (D420).

Экран «Рейтинги» показывает пиццерии кусками (Top/Bottom, зона риска, имена в
нарушениях); инструмент MCP отдаёт их списком по отбору. Числа — те же функции,
что у экрана: средние пиццерии по периодам рейтинга — `summary.unit_averages`,
карта — `maps_store.unit_scores`, агрегаторы — `agg_store.latest`. Своего
подсчёта здесь нет: только склейка по id пиццерии.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from src.db import agg_store, maps_store

from .model import RKO, RS
from .pointer import GOOGLE
from .summary import Fact, unit_averages


@dataclass(frozen=True)
class AggScore:
    aggregator: str
    score: float
    scale: int
    votes: int | None
    on_date: date


@dataclass(frozen=True)
class UnitView:
    unit: str
    name: str
    country: str
    rs: float | None
    rko: float | None
    #: Оценка Google на карте и число отзывов; `None` — пиццерия на карте не найдена.
    maps: tuple[float, int] | None
    aggregators: tuple[AggScore, ...]


def stitch(
    facts: Iterable[Fact],
    maps: dict[str, tuple[float, int]],
    aggs: Iterable[agg_store.LatestRating],
) -> tuple[UnitView, ...]:
    """Пиццерии с оценкой РС или РКО в фактах, по стране и имени. Карта и агрегаторы
    дописываются тем, у кого они есть: пиццерия без них остаётся в списке."""
    facts = list(facts)
    names = {f.unit: (f.unit_name, f.country) for f in facts}
    scores = {kind: unit_averages(facts, kind) for kind in (RS, RKO)}
    by_unit: dict[str, list[AggScore]] = {}
    for row in aggs:
        by_unit.setdefault(row.dodo_id, []).append(
            AggScore(row.aggregator, row.score, row.scale, row.votes, row.on_date)
        )
    views = [
        UnitView(
            unit,
            name,
            country,
            scores[RS].get(unit),
            scores[RKO].get(unit),
            maps.get(unit),
            tuple(sorted(by_unit.get(unit, ()), key=lambda a: a.aggregator)),
        )
        for unit, (name, country) in names.items()
    ]
    return tuple(sorted(views, key=lambda v: (v.country, v.name, v.unit)))


def load(facts: Sequence[Fact], countries: Sequence[str], *, until: date) -> tuple[UnitView, ...]:
    """Склейка с картой и агрегаторами на конец периода (как у экрана: не позже `until`)."""
    return stitch(
        facts,
        maps_store.unit_scores(GOOGLE, until=until),
        agg_store.latest(countries, until=until),
    )
