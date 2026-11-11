"""Small rating histories as geometry and adjacent changes, without grading.

Values remain in their source's scale and chronological order. Missing values
break both the line and the comparison; they never become zero. A minimum
relative span prevents numerical noise from looking like a full-height crash.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

WIDTH = 160.0
HEIGHT = 44.0
PAD = 5.0
MIN_RELATIVE_SPAN = 0.04


@dataclass(frozen=True)
class TrendScore:
    value: float | None
    delta: float | None
    arrow: str
    formatted: str
    delta_text: str
    tone: str


@dataclass(frozen=True)
class TrendPoint:
    x: float
    y: float
    value: float


@dataclass(frozen=True)
class Trend:
    width: float
    height: float
    paths: tuple[str, ...]
    points: tuple[TrendPoint, ...]
    scores: tuple[TrendScore, ...]
    low: float | None
    high: float | None


def build(scores: Sequence[float | None]) -> Trend:
    """Presentation only: a one-point history is a point, never a fabricated line."""
    values = tuple(
        float(value) if value is not None and math.isfinite(value) else None for value in scores
    )
    changes: list[TrendScore] = []
    previous: float | None = None
    for value in values:
        delta = value - previous if value is not None and previous is not None else None
        digits = 1 if value is not None and value > 5 else 2
        shown = round(delta, digits) + 0.0 if delta is not None else None
        changes.append(
            TrendScore(
                value,
                delta,
                "" if shown is None else "▲" if shown >= 0 else "▼",
                "—" if value is None else f"{value:.{digits}f}",
                "—" if shown is None else f"{shown:+.{digits}f}",
                "" if shown is None else "up" if shown >= 0 else "down",
            )
        )
        previous = value
    available = tuple(value for value in values if value is not None)
    if not available:
        return Trend(WIDTH, HEIGHT, (), (), tuple(changes), None, None)
    low, high = min(available), max(available)
    span = max(high - low, max(abs(low), abs(high), 1.0) * MIN_RELATIVE_SPAN)
    middle = (low + high) / 2
    bottom, top = middle - span / 2, middle + span / 2
    points: list[TrendPoint] = []
    paths: list[str] = []
    segment: list[TrendPoint] = []
    for i, value in enumerate(values):
        if value is None:
            if len(segment) > 1:
                paths.append(_path(segment))
            segment = []
            continue
        x = WIDTH / 2 if len(values) == 1 else PAD + i * (WIDTH - 2 * PAD) / (len(values) - 1)
        y = PAD + (top - value) / span * (HEIGHT - 2 * PAD)
        point = TrendPoint(round(x, 2), round(y, 2), value)
        points.append(point)
        segment.append(point)
    if len(segment) > 1:
        paths.append(_path(segment))
    return Trend(WIDTH, HEIGHT, tuple(paths), tuple(points), tuple(changes), bottom, top)


def _path(points: Sequence[TrendPoint]) -> str:
    return " ".join(
        f"{'M' if i == 0 else 'L'} {point.x:g} {point.y:g}" for i, point in enumerate(points)
    )
