"""Ответы API Swarm по рейтингам (#567, D335): чистая сборка над прочитанными строками.

Ни одного похода в базу: строки читает `src/db/swarm_read.py`, здесь они
раскладываются по периодам. Всё, что выровнено по `periods`, — список той же
длины и того же порядка (старые первыми), `None` — данных за период нет.
Топ нарушений считает та же функция, что сводка раздела «Рейтинги»
(`summary.violation_block`): нарушение — это «Выявленные нарушения» РКО и
замечания периода РС, «Другие проблемы» в топ не идут, пометка (ML)/(ИИ) и
регистр текст не различают. Второго правила подсчёта здесь нет.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from src.db.swarm_read import PeriodRow

from .model import (
    FORMAT_RKO_EVALUATIONS,
    FORMAT_RKO_VIOLATIONS,
    FORMAT_RS_CHECKUPS,
    FORMAT_SHEET_SCORES,
    FORMAT_SNAPSHOT,
    RKO,
    RS,
)
from .summary import ViolationFact, violation_block

#: Каналы проверки рейтинга (CHECK `ratings.checkups.channel`, 0038).
CHANNELS = ("restaurant", "delivery", "inspection", "online")

#: Какие загрузки питают ответ: их последнее время — `loaded_at`.
SCORE_FORMATS = (FORMAT_SNAPSHOT, FORMAT_SHEET_SCORES)
CHECKUP_FORMATS = {
    RS: (FORMAT_RS_CHECKUPS, FORMAT_SNAPSHOT),
    RKO: (FORMAT_RKO_VIOLATIONS, FORMAT_RKO_EVALUATIONS),
}
VIOLATION_FORMATS = {
    RS: (FORMAT_SNAPSHOT,),
    RKO: (FORMAT_RKO_VIOLATIONS, FORMAT_RKO_EVALUATIONS),
}


def iso_utc(moment: datetime | None) -> str | None:
    """`2026-10-08T19:40:00Z` — время в UTC без долей секунды."""
    if moment is None:
        return None
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def period_json(row: PeriodRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "start": row.begin_on.isoformat(),
        "end": row.end_on.isoformat(),
        "title_ru": row.title_ru,
        "title_en": row.title_en,
    }


def _slots(period_ids: Sequence[int]) -> dict[int, int]:
    return {pid: i for i, pid in enumerate(period_ids)}


def scores(period_ids: Sequence[int], rows: Iterable[Sequence[Any]]) -> list[dict[str, Any]]:
    """Строки `(unit, name, country, developer, period_id, score)` → пиццерии с баллами."""
    slot = _slots(period_ids)
    units: dict[str, dict[str, Any]] = {}
    for unit, name, country, developer, period_id, score in rows:
        entry = units.setdefault(
            unit,
            {
                "id": unit,
                "name": name,
                "cc": country,
                "developer": developer,
                "scores": [None] * len(period_ids),
            },
        )
        if period_id in slot:
            entry["scores"][slot[period_id]] = float(score)
    return list(units.values())


def checkups(
    period_ids: Sequence[int],
    by_channel: Iterable[Sequence[Any]],
    rated: Iterable[Sequence[Any]],
) -> list[dict[str, Any]]:
    """Собираемость по пиццериям: счётчики каналов и `rated` по периодам.

    `by_channel` — `(unit, name, country, period_id, channel, n)` из выгрузок,
    `rated` — `(unit, name, country, period_id, n)` из снимка. Ячейка `None` —
    в периоде нет ни проверок из выгрузок, ни числа из снимка.
    """
    slot = _slots(period_ids)
    units: dict[str, dict[str, Any]] = {}

    def cell(unit: str, name: str, country: str, period_id: int) -> dict[str, Any] | None:
        if period_id not in slot:
            return None
        entry = units.setdefault(
            unit, {"id": unit, "name": name, "cc": country, "counts": [None] * len(period_ids)}
        )
        counts = entry["counts"]
        if counts[slot[period_id]] is None:
            counts[slot[period_id]] = {**dict.fromkeys(CHANNELS, 0), "rated": None}
        found: dict[str, Any] = counts[slot[period_id]]
        return found

    for unit, name, country, period_id, channel, n in by_channel:
        found = cell(unit, name, country, period_id)
        if found is not None and channel in CHANNELS:
            found[channel] += int(n)
    for unit, name, country, period_id, n in rated:
        found = cell(unit, name, country, period_id)
        if found is not None:
            found["rated"] = int(n)
    return sorted(units.values(), key=lambda u: (u["cc"], u["name"], u["id"]))


def violations(
    period_ids: Sequence[int],
    facts: Iterable[Sequence[Any]],
    checkup_counts: Iterable[Sequence[Any]],
    *,
    top: int,
) -> list[dict[str, Any]]:
    """Топ нарушений страны по периодам.

    `facts` — `(period_id, unit, name, country, text, parent, category, amount)`,
    `checkup_counts` — `(country, period_id, n)`. Ячейка периода — `None`, если у
    страны в нём нет ни проверок, ни нарушений; `{"total": 0, …}` — проверки были,
    нарушений нет.
    """
    slot = _slots(period_ids)
    by_cell: dict[tuple[str, int], list[ViolationFact]] = {}
    counts: dict[tuple[str, int], int] = {}
    for period_id, unit, name, country, text, parent, category, amount in facts:
        if period_id in slot:
            by_cell.setdefault((country, period_id), []).append(
                ViolationFact(unit, name, country, text, parent, category, int(amount))
            )
    for country, period_id, n in checkup_counts:
        if period_id in slot:
            counts[(country, period_id)] = int(n or 0)
    countries = sorted({key[0] for key in (*by_cell, *counts)})
    return [
        {
            "cc": country,
            "periods": [_violation_cell(country, pid, by_cell, counts, top) for pid in period_ids],
        }
        for country in countries
    ]


def _violation_cell(
    country: str,
    period_id: int,
    by_cell: dict[tuple[str, int], list[ViolationFact]],
    counts: dict[tuple[str, int], int],
    top: int,
) -> dict[str, Any] | None:
    key = (country, period_id)
    if key not in by_cell and key not in counts:
        return None
    block = violation_block(by_cell.get(key, []), checkups=counts.get(key, 0), limit=top)
    return {
        "total": block.total,
        "checkups": block.checkups,
        "per_checkup": block.per_checkup,
        "top": [{"text": line.text, "count": line.count} for line in block.top],
    }
