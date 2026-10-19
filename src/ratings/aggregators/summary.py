"""Сводка оценок агрегаторов по группам сводки (кластер, страна, срез).

**Как считается.** Оценка группы на агрегаторе — средняя по всем оценкам её
пиццерий: оценка точки взвешивается числом оценок, как у карт («4,8 по трём»
не перевешивает «4,2 по тысяче»). Точка, у которой агрегатор не отдаёт число
оценок, идёт с весом 1. **Шкала — родная агрегатора** (Wolt — из 10, Glovo —
%, остальные — из 5): в одну шкалу не сводим, иначе цифра разойдётся с тем,
что видит гость на витрине.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from src.db import agg_store
from src.db.agg_store import LatestRating

#: Порядок колонок блока: сначала крупные, дальше по алфавиту.
ORDER = ("wolt", "glovo", "bolt_food", "yandex_eda", "yemeksepeti", "trendyol_go")


@dataclass(frozen=True)
class AggScore:
    avg: float
    scale: int
    votes: int  # оценок всего (по точкам, где агрегатор их отдаёт)
    points: int  # пиццерий группы на агрегаторе


@dataclass(frozen=True)
class GroupAggs:
    group: str
    scores: dict[str, AggScore]
    as_of: date | None


def aggregators_of(rows: Iterable[LatestRating]) -> tuple[str, ...]:
    """Агрегаторы, у которых есть хоть одна оценка, — в порядке колонок."""
    present = {r.aggregator for r in rows}
    return tuple(a for a in ORDER if a in present) + tuple(sorted(present - set(ORDER)))


def summarize(
    rows: Iterable[LatestRating], groups: Sequence[tuple[str, Sequence[str]]]
) -> tuple[GroupAggs, ...]:
    by: dict[tuple[str, str], list[LatestRating]] = {}
    for row in rows:
        by.setdefault((row.country_code, row.aggregator), []).append(row)
    aggregators = sorted({a for _, a in by})
    result = []
    for key, members in groups:
        scores: dict[str, AggScore] = {}
        dates: list[date] = []
        for aggregator in aggregators:
            items = [r for c in members for r in by.get((c, aggregator), [])]
            if not items:
                continue
            weights = [max(r.votes or 1, 1) for r in items]
            avg = sum(r.score * w for r, w in zip(items, weights, strict=True)) / sum(weights)
            scores[aggregator] = AggScore(
                round(avg, 2 if items[0].scale <= 10 else 1),
                items[0].scale,
                sum(r.votes or 0 for r in items),
                len({r.dodo_id for r in items}),
            )
            dates += [r.on_date for r in items]
        result.append(GroupAggs(key, scores, max(dates) if dates else None))
    return tuple(result)


def for_groups(
    groups: Sequence[tuple[str, Sequence[str]]], *, until: date, today: date
) -> tuple[tuple[str, ...], tuple[GroupAggs, ...], bool]:
    """Оценки агрегаторов по группам на конец периода: (колонки, строки, взяты ли позже).

    Один путь для «Рейтингов» и «Главной» (D557). Истории у агрегаторов нет дальше
    первого сбора (11.10.2026): на прошлый период — последние собранные, и экран
    пишет, что они позже периода. База не ответила — `RatingsError` наверх.
    """
    countries = tuple(c for _, members in groups for c in members)
    rows = agg_store.latest(countries, until=until)
    later = not rows and until < today
    if later:
        rows = agg_store.latest(countries)
    return aggregators_of(rows), summarize(rows, groups), later
