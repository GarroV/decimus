"""Ответы API для сервисов (D426): оценки агрегаторов и топ нарушений по проверкам.

Чистая раскладка над прочитанными строками — ни одного похода в базу. Средние
агрегаторов считает та же функция, что блок «Оценки на картах и в агрегаторах»
(`aggregators.summary.summarize`): второго правила подсчёта здесь нет.
Персональных данных в ответах нет: пиццерия, страна, коды пунктов и числа.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.db.agg_store import LatestRating
from src.db.swarm_read import CountryInspections, FindingCount
from src.ratings.aggregators import summary as ragg

Titles = Mapping[str, tuple[str | None, str | None]]


def aggregator_list(rows: Sequence[LatestRating], names: Mapping[str, str]) -> list[dict[str, Any]]:
    """Агрегаторы с оценками — в порядке колонок страницы, со шкалой."""
    scales = {r.aggregator: r.scale for r in rows}
    return [
        {"key": key, "title": names.get(key, key), "scale": scales[key]}
        for key in ragg.aggregators_of(rows)
    ]


def aggregator_countries(
    rows: Sequence[LatestRating], countries: Sequence[str]
) -> list[dict[str, Any]]:
    """Средняя страны на каждом агрегаторе — как строка страны на «Рейтингах»."""
    groups = [(code, (code,)) for code in countries]
    return [
        {
            "cc": group.group,
            "as_of": group.as_of.isoformat() if group.as_of else None,
            "scores": {
                key: {
                    "avg": score.avg,
                    "scale": score.scale,
                    "votes": score.votes,
                    "pizzerias": score.points,
                }
                for key, score in sorted(group.scores.items())
            },
        }
        for group in ragg.summarize(rows, groups)
    ]


def aggregator_units(rows: Sequence[LatestRating]) -> list[dict[str, Any]]:
    """Последняя оценка каждой точки, привязанной к пиццерии."""
    return [
        {
            "dodo_id": r.dodo_id,
            "cc": r.country_code,
            "aggregator": r.aggregator,
            "score": r.score,
            "scale": r.scale,
            "votes": r.votes,
            "on": r.on_date.isoformat(),
        }
        for r in sorted(rows, key=lambda r: (r.country_code, r.dodo_id, r.aggregator))
    ]


def _top(by_code: Mapping[str, tuple[int, int]], titles: Titles, top: int) -> list[dict[str, Any]]:
    """Самые частые пункты: чаще записан — выше; поровну — в большем числе
    проверок; дальше по коду, чтобы порядок не плясал между запросами."""
    ordered = sorted(by_code.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
    return [
        {
            "code": code,
            "title_ru": titles.get(code.strip().upper(), (None, None))[0],
            "title_en": titles.get(code.strip().upper(), (None, None))[1],
            "findings": findings,
            "inspections": inspections,
        }
        for code, (findings, inspections) in ordered[:top]
    ]


def inspection_violations(
    counts: Sequence[FindingCount],
    totals: Sequence[CountryInspections],
    *,
    top: int,
    titles_of: Callable[[str], Titles],
) -> dict[str, Any]:
    """Топ записей принятых проверок: по стране и по всему охвату запроса.

    `inspections` у пункта по сети — сумма по странам: проверка принадлежит
    одной пиццерии, а значит одной стране, и дважды не считается. Подписи —
    из методики самой свежей проверки страны; для сети — из первой по коду
    страны, где пункт подписан."""
    by_country: dict[str, dict[str, tuple[int, int]]] = {}
    network: dict[str, tuple[int, int]] = {}
    for row in counts:
        by_country.setdefault(row.country, {})[row.code] = (row.findings, row.inspections)
        was = network.get(row.code, (0, 0))
        network[row.code] = (was[0] + row.findings, was[1] + row.inspections)
    titles = {t.country: titles_of(t.checklist_version) for t in totals}
    merged: dict[str, tuple[str | None, str | None]] = {}
    for t in sorted(totals, key=lambda t: t.country):
        for code, pair in titles[t.country].items():
            merged.setdefault(code, pair)
    return {
        "network": {
            "inspections": sum(t.inspections for t in totals),
            "top": _top(network, merged, top),
        },
        "countries": [
            {
                "cc": t.country,
                "inspections": t.inspections,
                "top": _top(by_country.get(t.country, {}), titles[t.country], top),
            }
            for t in sorted(totals, key=lambda t: t.country)
        ],
    }
