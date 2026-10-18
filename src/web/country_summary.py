"""Сводка экрана «Пиццерии» (D467): цифры периода и девелоперы стран.

Сводка нескольких стран — для отбора «Девелопер»: рабочая зона показывает
общие цифры его стран и строку на каждую. Среднее здесь — среднее проверок,
взвешенное числом проверок страны: так же, как считал бы один снимок по всем
этим проверкам сразу, поэтому «в одной стране» и «в сумме одной страны»
совпадают. РС / РКО / карты в общую сводку не входят: среднее группы у
рейтингов считается по пиццериям (D353) и из средних стран не складывается.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from src.db import ratings_read
from src.db.errors import DbError

from .overview import Overview

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Summary:
    """Цифры периода по одной стране или по нескольким сразу."""

    inspections: int
    units_checked: int
    units_total: int
    average: float | None
    #: Движение к такому же прошлому периоду; у суммы нескольких стран не
    #: показывается: прошлые окна считались отдельно, и сумма их средних — не среднее.
    average_delta: float | None
    grades: tuple[tuple[str, int], ...]
    #: Проверок с критическим нарушением (`Overview.critical_total`).
    critical: int = 0

    @property
    def has_inspections(self) -> bool:
        return self.inspections > 0


def summarize(snapshots: Sequence[Overview]) -> Summary:
    """Свести снимки стран в одну сводку; пустой список — пустая сводка."""
    inspections = sum(s.inspections_total for s in snapshots)
    weighted = sum((s.average or 0.0) * s.inspections_total for s in snapshots)
    grades: dict[str, int] = {}
    for snapshot in snapshots:
        for letter, count in snapshot.grades:
            grades[letter] = grades.get(letter, 0) + count
    one = snapshots[0] if len(snapshots) == 1 else None
    return Summary(
        inspections=inspections,
        units_checked=sum(s.units_checked for s in snapshots),
        units_total=sum(s.units_total for s in snapshots),
        average=round(weighted / inspections, 1) if inspections else None,
        average_delta=one.average_delta if one else None,
        grades=tuple(sorted(grades.items())),
        critical=sum(s.critical_total for s in snapshots),
    )


def developers_of(codes: Sequence[str]) -> tuple[dict[str, tuple[str, ...]], dict[str, str], bool]:
    """Девелоперы стран из справочника рейтингов (`ratings.countries.developer`).

    Возвращает `({девелопер: коды его стран}, {код страны: девелопер}, сбой)` по
    странам `codes` — те, что видит вошедший. Страна без девелопера в справочнике
    ни в одну группу не попадает. Сбой чтения — пусто и отметка: фильтр не
    рисуется, а экран остаётся.
    """
    try:
        rows = ratings_read.countries()
    except DbError:
        log.warning("Девелоперы стран не прочитались", exc_info=True)
        return {}, {}, True
    visible = set(codes)
    by_dev: dict[str, list[str]] = {}
    by_country: dict[str, str] = {}
    for row in rows:
        name = (row.developer or "").strip()
        if name and row.code in visible:
            by_dev.setdefault(name, []).append(row.code)
            by_country[row.code] = name
    order = {code: i for i, code in enumerate(codes)}
    return (
        {
            name: tuple(sorted(members, key=lambda c: order[c]))
            for name, members in sorted(by_dev.items())
        },
        by_country,
        False,
    )
