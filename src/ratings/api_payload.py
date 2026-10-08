"""Ответы API `/api/v1/ratings/*` (#567): чтение → формы JSON контракта.

Не чистый модуль, как и `report`: ходит в базу дверью `src.db.ratings_read`.
Ничего не пересчитывает иначе, чем сводка: баллы — как лежат, топ нарушений —
`summary.violation_block` (то же схлопывание текстов и тот же порядок, что на
экране). Параметры уже проверены вызывающим (`src/web/api.py`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date
from typing import Any

from src.db import ratings_read as read
from src.db.ratings_read import PeriodRow

from .summary import ViolationFact, normalize_text, violation_block

#: Предел периодов в одном ответе: три года недель РКО. Больше — 400 с просьбой
#: сузить даты: ответ растёт как «пиццерии × периоды».
MAX_PERIODS = 156

#: Каналы собираемости — ключи контракта, все четыре в каждой ячейке.
CHANNELS = ("restaurant", "delivery", "inspection", "online")


class RangeTooLargeError(ValueError):
    """Периодов в запрошенных датах больше `MAX_PERIODS`."""


@dataclass(frozen=True)
class Query:
    rating_type: str
    countries: tuple[str, ...]
    begin: date | None
    end: date | None


def _periods(q: Query) -> tuple[PeriodRow, ...]:
    found = read.periods_between(q.rating_type, begin=q.begin, end=q.end, limit=MAX_PERIODS + 1)
    if len(found) > MAX_PERIODS:
        raise RangeTooLargeError(str(MAX_PERIODS))
    return found


def _period_json(p: PeriodRow) -> dict[str, Any]:
    return {
        "id": p.id,
        "start": p.begin_on.isoformat(),
        "end": p.end_on.isoformat(),
        "title_ru": p.title_ru,
        "title_en": p.title_en,
    }


def _loaded_at() -> str | None:
    loaded = read.last_loaded().values()
    if not loaded:
        return None
    return max(loaded).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def scores(q: Query) -> dict[str, Any]:
    periods = _periods(q)
    ids = [p.id for p in periods]
    position = {pid: i for i, pid in enumerate(ids)}
    developers = {row.code: row.developer for row in read.countries()}
    units: dict[str, dict[str, Any]] = {}
    facts = (
        read.score_facts(countries=q.countries, begin=date.min, end=date.max, period_ids=ids)
        if ids
        else []
    )
    for unit, name, country, rating_type, period_id, _, score in facts:
        if rating_type != q.rating_type:
            continue
        line = units.setdefault(
            unit,
            {
                "id": unit,
                "name": name,
                "cc": country,
                "developer": developers.get(country),
                "scores": [None] * len(ids),
            },
        )
        line["scores"][position[period_id]] = score
    return {
        "type": q.rating_type,
        "periods": [_period_json(p) for p in periods],
        "units": sorted(units.values(), key=lambda u: (u["cc"], u["name"], u["id"])),
        "loaded_at": _loaded_at(),
    }


def checkups(q: Query) -> dict[str, Any]:
    periods = _periods(q)
    ids = [p.id for p in periods]
    position = {pid: i for i, pid in enumerate(ids)}
    units: dict[str, dict[str, Any]] = {}
    rows = read.checkup_counts(q.rating_type, countries=q.countries, period_ids=ids) if ids else []
    for unit, country, period_id, channel, count in rows:
        if channel not in CHANNELS:
            continue
        line = units.setdefault(unit, {"id": unit, "cc": country, "counts": [None] * len(ids)})
        cell = line["counts"][position[period_id]]
        if cell is None:
            cell = dict.fromkeys(CHANNELS, 0)
            line["counts"][position[period_id]] = cell
        cell[channel] += count
    return {
        "type": q.rating_type,
        "periods": [_period_json(p) for p in periods],
        "units": sorted(units.values(), key=lambda u: (u["cc"], u["id"])),
    }


def _criterion(texts: Sequence[tuple[str, str | None]], line_text: str) -> str | None:
    """Код критерия строки топа: самый частый среди её фактов; нет кода — `None`."""
    key = normalize_text(line_text)
    codes = Counter(code for text, code in texts if code and normalize_text(text) == key)
    if not codes:
        return None
    return min(codes.items(), key=lambda item: (-item[1], item[0]))[0]


def violations(q: Query, *, top: int) -> dict[str, Any]:
    periods = _periods(q)
    ids = [p.id for p in periods]
    rows = (
        read.period_violations(q.rating_type, countries=q.countries, period_ids=ids) if ids else []
    )
    facts: dict[tuple[str, int], list[ViolationFact]] = defaultdict(list)
    codes: dict[tuple[str, int], list[tuple[str, str | None]]] = defaultdict(list)
    for period_id, country, text, category, amount, criterion in rows:
        facts[(country, period_id)].append(
            ViolationFact("", "", country, text, None, category, amount)
        )
        codes[(country, period_id)].append((text, criterion))
    out = []
    for country in q.countries:
        per_period = []
        for pid in ids:
            block = violation_block(facts.get((country, pid), []), checkups=0, limit=top)
            per_period.append(
                [
                    {
                        "text": line.text,
                        "criterion_id": _criterion(codes.get((country, pid), []), line.text),
                        "count": line.count,
                    }
                    for line in block.top
                ]
            )
        out.append({"cc": country, "top": per_period})
    return {"type": q.rating_type, "periods": [_period_json(p) for p in periods], "countries": out}
