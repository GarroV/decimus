"""Сравнение девелоперов и стран рядом (D551, #972) — только для УК.

Срез «Рейтингов» показывает одну группу; руководству не хватало видеть всех
девелоперов и все страны одной таблицей за тот же период. Числа считаются
тем же правилом, что и сводка среза (`summary.group_average`): средняя
пиццерий группы, а не средняя средних по странам — иначе у девелопера с
одной большой и одной маленькой страной итог расходился бы со срезом.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.db.ratings_read import CountryRow

from .model import RKO, RS
from .periods import previous_period
from .report import Choices, Selection, period_facts
from .summary import Fact, delta, group_average


@dataclass(frozen=True)
class Line:
    """Строка сравнения: девелопер (`key` — имя) или страна (`key` — код)."""

    key: str
    countries: tuple[str, ...]
    #: Пиццерий с оценкой РС или РКО за период.
    units: int
    rs: float | None
    rs_delta: float | None
    rko: float | None
    rko_delta: float | None


@dataclass(frozen=True)
class Comparison:
    developers: tuple[Line, ...]
    countries: tuple[Line, ...]


def _line(
    key: str, codes: tuple[str, ...], current: Sequence[Fact], before: Sequence[Fact]
) -> Line:
    now = {k: group_average(current, k, codes) for k in (RS, RKO)}
    was = {k: group_average(before, k, codes) for k in (RS, RKO)}
    return Line(
        key=key,
        countries=codes,
        units=len({f.unit for f in current if f.country in codes}),
        rs=now[RS],
        rs_delta=delta(now[RS], was[RS]),
        rko=now[RKO],
        rko_delta=delta(now[RKO], was[RKO]),
    )


def _ranked(rows: list[Line]) -> tuple[Line, ...]:
    """Лучший РС сверху; без оценки — внизу, по ключу: таблица сравнивает, а не перечисляет."""
    return tuple(sorted(rows, key=lambda x: (x.rs is None, -(x.rs or 0.0), x.key)))


def lines(
    countries: Sequence[CountryRow], current: Sequence[Fact], before: Sequence[Fact]
) -> Comparison:
    """Строки сравнения по фактам текущего и прошлого периода. Без базы."""
    developers: dict[str, list[str]] = {}
    for row in countries:
        if row.developer:
            developers.setdefault(row.developer, []).append(row.code)
    return Comparison(
        developers=_ranked(
            [_line(name, tuple(codes), current, before) for name, codes in developers.items()]
        ),
        countries=_ranked([_line(row.code, (row.code,), current, before) for row in countries]),
    )


def build(selection: Selection, found: Choices) -> Comparison:
    """Сравнение за период выбранного среза по всем странам охвата IMF."""
    codes = tuple(row.code for row in found.countries)
    prev = previous_period(selection.period, rs_periods=found.rs_periods)
    current, before = period_facts(codes, selection.period, prev)
    return lines(found.countries, current, before)
