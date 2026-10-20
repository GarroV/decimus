"""Один заход загрузки: подразделения → результаты по пиццериям → агрегаты → база.

Результаты читаются по одной пиццерии (фильтр `departmentIds` вложенных подразделений не
включает), сворачиваются в счётчики сразу и забываются: в памяти одновременно результаты
одной пиццерии, дальше — только `Counters` (D575). Страна и сеть в базу не пишутся — это
суммы пиццерий, их складывает чтение.

Сбой на любой пиццерии роняет заход целиком: снимок, где половина пиццерий пустая,
выглядел бы как «обученность упала». Прежний снимок остаётся, заход повторится.

Что уходит в лог — только числа и названия подразделений.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.db import learning_store
from src.domain.training_metrics import Counters, aggregate
from src.ratings.matching import KnownUnit

from . import departments
from .ispring import Client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Summary:
    """Итог захода — числа для журнала и вывода команды."""

    departments: int
    pizzerias: int
    matched: int
    results: int
    dropped: int
    ignored: int


def run(client: Client, *, today: date | None = None) -> Summary:
    """Забрать подразделения и результаты, свернуть и положить снимок за `today` (UTC)."""
    on_date = today or datetime.now(UTC).date()
    known = [KnownUnit(*row) for row in learning_store.known_units()]
    mapped, ignored = departments.map_departments(client.departments(), known)
    pizzerias = [m for m in mapped if m.kind == departments.KIND_PIZZERIA]
    totals: dict[str, Counters] = {}
    by_course: dict[tuple[str, str], Counters] = {}
    titles: dict[str, str] = {}
    results = dropped = 0
    for index, unit in enumerate(pizzerias, 1):
        rows, unit_titles, bad = client.results(unit.id)
        agg = aggregate(rows)
        totals[unit.id] = agg.total
        by_course.update({(unit.id, course): c for course, c in agg.courses.items()})
        titles.update(unit_titles)
        results += len(rows)
        dropped += bad
        logger.info(
            "Обучение: %d/%d %s — назначений %d", index, len(pizzerias), unit.title, len(rows)
        )
    # Курс без названия в ответе (поле необязательное для читателя) называется своим кодом.
    for _, course in by_course:
        titles.setdefault(course, course)
    learning_store.save_snapshot(
        on_date,
        [(m.id, m.title, m.kind, m.country_code, m.parent_id, m.unit_dodo_id) for m in mapped],
        totals,
        by_course,
        titles,
    )
    matched = sum(1 for m in pizzerias if m.unit_dodo_id)
    return Summary(len(mapped), len(pizzerias), matched, results, dropped, ignored)
