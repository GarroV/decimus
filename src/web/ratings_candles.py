"""Свечи кластеров раздела «Рейтинги» (D383, D384): раскладка для SVG.

Свеча — месяц: средняя группы по периодам рейтинга, начавшимся в месяце
(первая, наибольшая, наименьшая, последняя — `src.ratings.summary.candles`).
Здесь только геометрия: шкала по вертикали общая для всех строк одного вида
рейтинга, чтобы строки сравнивались на глаз; оценки не пересчитываются.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.ratings.summary import Candle

WIDTH = 240.0
HEIGHT = 64.0
TOP_PAD = 4.0
BOTTOM_PAD = 4.0
BODY_SHARE = 0.56  # ширина тела свечи от шага месяца
MIN_BODY = 1.5  # плоская свеча всё равно видна черточкой
SCALE_TOP = 100.0
SCALE_STEP = 5  # нижний край шкалы — кратно пяти
SCALE_MARGIN = 1.0
MONTHS = {
    "ru": ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}


@dataclass(frozen=True)
class Stick:
    x: float  # центр, единицы viewBox
    width: float
    wick_top: float
    wick_bottom: float
    body_top: float
    body_height: float
    trend: str  # up | down | flat
    title: str
    in_period: bool  # месяц входит в выбранный период


@dataclass(frozen=True)
class Scale:
    low: float
    high: float
    threshold_y: float | None
    ticks: tuple[tuple[str, float], ...]  # подпись, y


def month_label(month: date, lang: str) -> str:
    return MONTHS.get(lang, MONTHS["en"])[month.month - 1]


def scale(series: Sequence[Sequence[Candle | None]], threshold: float) -> Scale:
    """Общая шкала для строк одного вида рейтинга: от кратного пяти ниже
    наименьшего до 100."""
    lows = [c.low for s in series for c in s if c is not None]
    if not lows:
        return Scale(SCALE_TOP - 10, SCALE_TOP, None, ())
    low = float(
        min(
            math.floor((min(lows) - SCALE_MARGIN) / SCALE_STEP) * SCALE_STEP, SCALE_TOP - SCALE_STEP
        )
    )
    result = Scale(low, SCALE_TOP, None, ())
    ticks = tuple((f"{v:g}", y(result, v)) for v in (low, SCALE_TOP))
    thr = y(result, threshold) if low < threshold < SCALE_TOP else None
    return Scale(result.low, result.high, thr, ticks)


def y(sc: Scale, value: float) -> float:
    span = sc.high - sc.low or 1.0
    usable = HEIGHT - TOP_PAD - BOTTOM_PAD
    return round(TOP_PAD + (sc.high - min(max(value, sc.low), sc.high)) / span * usable, 2)


def sticks(
    candles: Sequence[Candle | None],
    sc: Scale,
    *,
    period: tuple[date, date],
    lang: str,
    title: str,
) -> tuple[Stick, ...]:
    """Свечи одной строки; `title` — шаблон подписи с полями o, h, l, c, n, m."""
    step = WIDTH / max(len(candles), 1)
    out = []
    for i, candle in enumerate(candles):
        if candle is None:
            continue
        top, bottom = y(sc, max(candle.open, candle.close)), y(sc, min(candle.open, candle.close))
        diff = round(candle.close, 1) - round(candle.open, 1)
        out.append(
            Stick(
                x=round(step * (i + 0.5), 2),
                width=round(step * BODY_SHARE, 2),
                wick_top=y(sc, candle.high),
                wick_bottom=y(sc, candle.low),
                body_top=top,
                body_height=max(round(bottom - top, 2), MIN_BODY),
                trend="up" if diff > 0 else "down" if diff < 0 else "flat",
                title=title.format(
                    m=f"{month_label(candle.month, lang)} {candle.month.year}",
                    o=f"{candle.open:.1f}",
                    h=f"{candle.high:.1f}",
                    l=f"{candle.low:.1f}",
                    c=f"{candle.close:.1f}",
                    n=candle.periods,
                ),
                in_period=period[0] <= candle.month <= period[1],
            )
        )
    return tuple(out)
