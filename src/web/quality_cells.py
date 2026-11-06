"""Ячейки таблицы «Качества»: текст значения, движение к прошлому месяцу, подсветка.

Одна таблица на страны и на пиццерии: столбцы одни (`COLUMNS`), значения приходят из
`quality_data` (`values` пиццерии или страны). Итог и веса — D719: итог красится как прочие
оценки (хуже прошлого месяца), веса — никак. Подсветка по D677: РКО и РС — по порогам
«Рейтингов» (ниже 80 красный, ниже 90 жёлтый, D552), остальные показатели — только если стали
хуже прошлого месяца; доли заказов направления «лучше/хуже» не имеют и не подсвечиваются.
Пока месяц идёт, выручка без движения и без подсветки: неполный месяц против полного прошлого
всегда «падение» (D707).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal

from .ratings_line import tone as score_tone

DASH = "—"
#: Движение выручки меньше половины процента — «без изменений».
HALF = Decimal(1) / 2


@dataclass(frozen=True)
class Delta:
    text: str
    #: `up`, `down`, `flat` или пусто (нет прошлого месяца).
    kind: str


@dataclass(frozen=True)
class Column:
    key: str
    #: `score` (число со знаками), `share` (доля заказов, проценты), `money` (выручка),
    #: `weight` (вес компонента в итоге, проценты, без движения и подсветки).
    kind: str
    places: int = 1
    #: РКО и РС красятся по порогам рейтингов, остальные — по ухудшению.
    threshold: bool = False
    audit: bool = False
    #: Группа верхнего этажа шапки (`total`, `weights`, `ratings`, `guest`, `shares`,
    #: `revenue`); пусто — без группы.
    group: str = ""


COLUMNS = (
    Column("total", "score", 2, group="total"),
    Column("w_rko", "weight", group="weights"),
    Column("w_kr", "weight", group="weights"),
    Column("w_maps", "weight", group="weights"),
    Column("w_aggs", "weight", group="weights"),
    Column("rko", "score", 1, threshold=True, group="ratings"),
    Column("rs", "score", 1, threshold=True, group="ratings"),
    Column("checks", "score", 1, group="ratings"),
    Column("kr", "score", 2, group="guest"),
    Column("maps", "score", 2, group="guest"),
    Column("aggs", "score", 2, group="guest"),
    Column("share_agg", "share", group="shares"),
    Column("share_app", "share", group="shares"),
    Column("share_other", "share", group="shares"),
    Column("rev_dine", "money", group="revenue"),
    Column("rev_delivery", "money", group="revenue"),
    Column("audit", "score", 1, audit=True),
)


def shown(show_audit: bool) -> tuple[Column, ...]:
    """Столбцы, которые видит читатель: проверка — только тому, кому она открыта."""
    return tuple(c for c in COLUMNS if show_audit or not c.audit)


def group_starts(columns: tuple[Column, ...]) -> tuple[bool, ...]:
    """Для каждого столбца: он первый в своей группе (слева от него — тонкая линия)."""
    return tuple(i == 0 or c.group != columns[i - 1].group for i, c in enumerate(columns))


@dataclass(frozen=True)
class Cell:
    text: str
    delta: Delta
    #: Подсветка: пусто, `bad`, `mid` (пороги рейтингов) или `worse` (хуже прошлого месяца).
    tone: str
    #: Первый столбец группы шапки: слева от ячейки тонкая линия.
    edge: bool = False
    #: Сумма весов итога («70%»), когда итог неполный: экран пишет под числом пометку; иначе пусто.
    incomplete: str = ""


def num(value: Decimal | None, places: int = 2) -> str:
    """Число с заданным числом знаков; нет данных — прочерк, а не ноль."""
    return DASH if value is None else f"{value:.{places}f}"


def pct(value: Decimal | None) -> str:
    return DASH if value is None else f"{value * 100:.0f}%"


def money(value: Decimal | None, currency: str | None) -> str:
    if value is None:
        return DASH
    text = f"{value:,.0f}".replace(",", " ")
    return f"{text} {currency}" if currency else text


def delta(now: Decimal | None, before: Decimal | None, places: int) -> Delta:
    """Движение к прошлому месяцу в единицах значения; нет одного из двух чисел — пусто."""
    if now is None or before is None:
        return Delta("", "")
    diff = now - before
    limit = Decimal(1) / (Decimal(10) ** places) / 2
    if abs(diff) < limit:
        return Delta(f"{0:.{places}f}", "flat")
    return Delta(f"{diff:+.{places}f}", "up" if diff > 0 else "down")


def delta_percent(now: Decimal | None, before: Decimal | None) -> Delta:
    """Движение выручки в процентах от прошлого месяца."""
    if now is None or not before:
        return Delta("", "")
    change = (now - before) / before * 100
    if abs(change) < HALF:
        return Delta("0%", "flat")
    return Delta(f"{change:+.0f}%", "up" if change > 0 else "down")


def _tone(column: Column, now: Decimal | None, move: Delta) -> str:
    if now is not None and column.threshold:
        found = score_tone(float(now))
        return "" if found == "good" else found
    if column.kind != "share" and move.kind == "down":
        return "worse"
    return ""


def cell(
    column: Column,
    now: Decimal | None,
    before: Decimal | None,
    currency: str | None,
    *,
    in_progress: bool = False,
) -> Cell:
    """Ячейка столбца: значение, движение и подсветка. Идущий месяц выручку не сравнивает."""
    if column.kind == "share":
        scaled = None if now is None else now * 100
        prior = None if before is None else before * 100
        return Cell(pct(now), delta(scaled, prior, 0), "")
    if column.kind == "weight":
        return Cell(pct(now), Delta("", ""), "")
    if column.kind == "money":
        move = Delta("", "") if in_progress else delta_percent(now, before)
        return Cell(money(now, currency), move, _tone(column, now, move))
    move = delta(now, before, column.places)
    return Cell(num(now, column.places), move, _tone(column, now, move))


def _incomplete(column: Column, values: Mapping[str, Decimal | None]) -> str:
    """Пометка у итога: сумма весов меньше 100% — итог нормирован на неё (D719)."""
    weights = values.get("w_sum")
    if column.key != "total" or values.get("total") is None or weights is None or weights >= 1:
        return ""
    return pct(weights)


def cells(
    now: Mapping[str, Decimal | None],
    before: Mapping[str, Decimal | None] | None,
    currency: str | None,
    *,
    show_audit: bool,
    in_progress: bool = False,
) -> tuple[Cell, ...]:
    """Ячейки строки по `COLUMNS`; столбец проверки — только тому, кто её видит."""
    columns = shown(show_audit)
    return tuple(
        replace(
            cell(
                c,
                now.get(c.key),
                None if before is None else before.get(c.key),
                currency,
                in_progress=in_progress,
            ),
            edge=edge,
            incomplete=_incomplete(c, now),
        )
        for c, edge in zip(columns, group_starts(columns), strict=True)
    )
