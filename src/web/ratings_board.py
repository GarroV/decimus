"""Табло стран раздела «Рейтинги»: шкала оценки вместо стены цифр.

Каждая страна — строка с двумя шкалами (РС и РКО). На шкале порог Top/Bottom,
бледная точка прошлого периода и цветной след до текущей: видно и где страна,
и куда сдвинулась. Итог группы — первой строкой.

Здесь только раскладка: оценки и дельты приходят готовыми из
`src.ratings.summary` (CLAUDE.md: «оценку не считать заново»). Прошлое
значение для точки — текущее минус показанная дельта, ровно то, что на экране.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from src.ratings.summary import CountryLine

SCALE_TOP = 100.0
SCALE_MARGIN = 3.0  # запас слева от самой низкой точки, баллы
SCALE_FLOOR_STEP = 5  # левый край шкалы — кратно пяти
TICKS_FINE = 5  # шаг делений на узкой шкале
TICKS_WIDE = 10
WIDE_SPAN = 30  # шире — деления через 10
SORTS = ("name", "rs", "rko")


@dataclass(frozen=True)
class Track:
    value: float | None
    delta: float | None
    cur: float  # положение точки, % ширины шкалы
    prev: float | None
    trend: str  # up | down | flat | none


@dataclass(frozen=True)
class Row:
    code: str
    name: str
    rs: Track
    rko: Track
    is_total: bool


@dataclass(frozen=True)
class Board:
    rows: tuple[Row, ...]
    ticks: tuple[tuple[int, float], ...]
    threshold: float  # положение порога, %
    sort: str


def _previous(value: float | None, d: float | None) -> float | None:
    return None if value is None or d is None else value - round(d, 1)


def _lowest(lines: Sequence[CountryLine], threshold: float) -> float:
    seen = [threshold]
    for line in lines:
        for value, d in ((line.rs, line.rs_delta), (line.rko, line.rko_delta)):
            seen += [v for v in (value, _previous(value, d)) if v is not None]
    low = min(seen) - SCALE_MARGIN
    return max(0.0, math.floor(low / SCALE_FLOOR_STEP) * SCALE_FLOOR_STEP)


def _place(value: float, low: float) -> float:
    span = SCALE_TOP - low
    return round(min(max((value - low) / span, 0.0), 1.0) * 100, 2)


def _track(value: float | None, d: float | None, low: float) -> Track:
    if value is None:
        return Track(None, None, 0.0, None, "none")
    before = _previous(value, d)
    shown = None if d is None else round(d, 1)
    trend = "flat" if not shown else ("up" if shown > 0 else "down")
    return Track(
        value,
        d,
        _place(value, low),
        None if before is None else _place(before, low),
        trend if d is not None else "none",
    )


def _row(line: CountryLine, name: str, low: float, *, is_total: bool) -> Row:
    return Row(
        line.country,
        name,
        _track(line.rs, line.rs_delta, low),
        _track(line.rko, line.rko_delta, low),
        is_total,
    )


def _ordered(
    lines: Sequence[CountryLine], sort: str, name: Callable[[str], str]
) -> list[CountryLine]:
    if sort == "name":
        return list(lines)
    def weakest_first(line: CountryLine) -> tuple[bool, float, str]:
        # Слабые сверху; без оценки — в конце, по имени.
        value = line.rs if sort == "rs" else line.rko
        return (value is None, value or 0.0, name(line.country))

    return sorted(lines, key=weakest_first)


def build(
    lines: Sequence[CountryLine],
    total: CountryLine,
    *,
    threshold: float,
    sort: str,
    name: Callable[[str], str],
    total_name: str,
) -> Board:
    sort = sort if sort in SORTS else SORTS[0]
    low = _lowest((*lines, total), threshold)
    step = TICKS_WIDE if SCALE_TOP - low > WIDE_SPAN else TICKS_FINE
    first = int(math.ceil(low / step) * step)
    ticks = tuple((v, _place(v, low)) for v in range(first, int(SCALE_TOP) + 1, step))
    ordered = _ordered(lines, sort, name)
    rows = [_row(line, name(line.country), low, is_total=False) for line in ordered]
    if len(lines) > 1:
        rows.insert(0, _row(total, total_name, low, is_total=True))
    return Board(tuple(rows), ticks, _place(threshold, low), sort)
