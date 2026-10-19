"""График средних раздела «Рейтинги» (D396): линия по периодам рейтинга.

Точка — один период рейтинга, попавший в выбранную рамку (`summary.points`):
период РС — полмесяца, РКО — неделя. Под графиком — подписи периодов, чтобы
было видно, в какие промежутки скачет линия. Свечи по месяцам (D384) сняты
11.10.2026: «про свечи, я понял, хуёвой идеи».

Здесь только геометрия, оценки не пересчитываются. Линия — SVG, растянутый по
ширине; точки и подписи — HTML поверх него в процентах, иначе растянутый
viewBox сплющил бы кружки и буквы.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.ratings.summary import Point

WIDTH = 240.0
HEIGHT = 80.0
TOP_PAD = 6.0
BOTTOM_PAD = 6.0
SCALE_TOP = 100.0
MIN_SPAN = 4  # самая узкая шкала, баллы: меньше — шум выглядит обвалом
SCALE_MARGIN = 1.0
MAX_LABELS = 6  # больше подписей под графиком не помещается на телефоне
#: Цвет по значению (D552): ниже 80 — красный, от 80 до 90 — жёлтый, от 90 — зелёный.
TONE_BAD_BELOW = 80.0
TONE_GOOD_FROM = 90.0


@dataclass(frozen=True)
class Band:
    """Полоса фона графика в единицах viewBox: верх, высота, тон (bad / mid / good)."""

    top: float
    height: float
    tone: str


@dataclass(frozen=True)
class Scale:
    low: float
    high: float
    threshold_y: float | None
    bands: tuple[Band, ...] = ()


def tone(value: float) -> str:
    """Тон значения по D552."""
    if value < TONE_BAD_BELOW:
        return "bad"
    return "mid" if value < TONE_GOOD_FROM else "good"


def _bands(sc: Scale) -> tuple[Band, ...]:
    """Полосы тонов в пределах шкалы: от верха графика до низа, без пустых."""
    edges = [(SCALE_TOP + 1, "good"), (TONE_GOOD_FROM, "mid"), (TONE_BAD_BELOW, "bad")]
    out: list[Band] = []
    for i, (upper, name) in enumerate(edges):
        lower = edges[i + 1][0] if i + 1 < len(edges) else -1.0
        hi, lo = min(upper, sc.high), max(lower, sc.low)
        if hi <= lo:
            continue
        top = 0.0 if hi >= sc.high else y(sc, hi)
        bottom = HEIGHT if lo <= sc.low else y(sc, lo)
        out.append(Band(top, round(bottom - top, 2), name))
    return tuple(out)


@dataclass(frozen=True)
class Dot:
    left: float  # % ширины
    top: float  # % высоты
    title: str
    tone: str = "mid"  # тон значения (D552)


@dataclass(frozen=True)
class Line:
    path: str  # точки полилинии в единицах viewBox
    dots: tuple[Dot, ...]
    labels: tuple[tuple[float, str], ...]  # % ширины, подпись


def scale(values: Sequence[float], threshold: float) -> Scale:
    """Шкала строки по самим данным: от целого ниже наименьшего до целого выше
    наибольшего, не уже `MIN_SPAN` и не выше 100."""
    if not values:
        empty = Scale(SCALE_TOP - MIN_SPAN, SCALE_TOP, None)
        return Scale(empty.low, empty.high, None, _bands(empty))
    high = float(min(math.ceil(max(values) + SCALE_MARGIN), SCALE_TOP))
    low = float(math.floor(min(values) - SCALE_MARGIN))
    if high - low < MIN_SPAN:
        low = high - MIN_SPAN
    base = Scale(low, high, None)
    thr = y(base, threshold) if low < threshold < high else None
    return Scale(low, high, thr, _bands(base))


def y(sc: Scale, value: float) -> float:
    span = sc.high - sc.low or 1.0
    usable = HEIGHT - TOP_PAD - BOTTOM_PAD
    return round(TOP_PAD + (sc.high - min(max(value, sc.low), sc.high)) / span * usable, 2)


def span_label(begin: date, end: date) -> str:
    """Период словами коротко: «1–15.09», «28.09–04.10», «07.09» для одного дня."""
    if begin == end:
        return f"{begin:%d.%m}"
    if (begin.year, begin.month) == (end.year, end.month):
        return f"{begin.day}–{end:%d.%m}"
    return f"{begin:%d.%m}–{end:%d.%m}"


def _label_indexes(n: int) -> tuple[int, ...]:
    """Какие точки подписать: все, если влезают, иначе `MAX_LABELS` поровну от
    первой до последней — крайние подписаны всегда."""
    if n <= MAX_LABELS:
        return tuple(range(n))
    return tuple(sorted({round(k * (n - 1) / (MAX_LABELS - 1)) for k in range(MAX_LABELS)}))


def line(points: Sequence[Point], sc: Scale, *, title: str) -> Line:
    """Линия одной строки; `title` — шаблон подсказки точки с полями p, v, n."""
    n = len(points)
    xs = [(i + 0.5) / n for i in range(n)]  # доля ширины, точки по центрам шагов
    ys = [y(sc, p.avg) for p in points]
    shown = _label_indexes(n)
    return Line(
        path=" ".join(f"{x * WIDTH:.2f},{yy}" for x, yy in zip(xs, ys, strict=True)),
        dots=tuple(
            Dot(
                round(x * 100, 2),
                round(yy / HEIGHT * 100, 2),
                title.format(
                    p=f"{span_label(p.begin, p.end)}.{p.end.year}", v=f"{p.avg:.1f}", n=p.units
                ),
                tone(p.avg),
            )
            for x, yy, p in zip(xs, ys, points, strict=True)
        ),
        labels=tuple(
            (round(xs[i] * 100, 2), span_label(points[i].begin, points[i].end)) for i in shown
        ),
    )
