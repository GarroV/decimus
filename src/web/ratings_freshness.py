"""Таблица свежести под значком «?» у заголовка «Рейтингов» (D659).

Читает источники (по одному запросу на вид), отдаёт классификации `src.ratings.freshness`
и готовит строки для шаблона: подписи, период, время прихода. Цвет — не здесь.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.db import agg_store, maps_store
from src.db import ratings_read as read
from src.db.errors import RatingsError
from src.ratings import freshness as fresh
from src.web.texts import t

logger = logging.getLogger(__name__)

_AT = "%d.%m %H:%M"


@dataclass(frozen=True)
class FreshLine:
    """Готовая строка таблицы: `status` — код цвета для класса, `word` — его слово."""

    status: str
    word: str
    name: str
    scope: str
    arrived: str


@dataclass(frozen=True)
class FreshTable:
    lines: tuple[FreshLine, ...]
    worst: str
    worst_word: str


def _day(d: date) -> str:
    return d.strftime("%d.%m")


def _span(begin: date, end: date) -> str:
    """`1–15.10` в одном месяце, `28.09–04.10` через границу месяцев."""
    if (begin.year, begin.month) == (end.year, end.month):
        return f"{begin.day}–{end.strftime('%d.%m')}"
    return f"{_day(begin)}–{_day(end)}"


def _scope(row: fresh.Row, lang: str) -> str:
    if row.kind in (fresh.KIND_RS, fresh.KIND_RKO) and row.begin_on and row.end_on:
        span = _span(row.begin_on, row.end_on)
        return t(f"ratings.fresh.scope.{row.kind}", lang, span=span)
    if row.kind in (fresh.KIND_RS, fresh.KIND_RKO):
        return t("ratings.fresh.none", lang)
    return t(f"ratings.fresh.scope.{row.kind}", lang)


def _name(row: fresh.Row, lang: str, agg_names: dict[str, str]) -> str:
    if row.kind == fresh.KIND_AGG:
        return agg_names.get(row.code, row.code)
    return t(f"ratings.fresh.name.{row.kind}", lang)


def _arrived(row: fresh.Row, lang: str) -> str:
    if row.arrived is None:
        return t("ratings.fresh.never", lang)
    return row.arrived.astimezone(fresh.local_zone()).strftime(_AT)


def lines_of(
    rows: tuple[fresh.Row, ...], lang: str, agg_names: dict[str, str]
) -> FreshTable | None:
    """Строки для шаблона и худший цвет; `None` — строк нет."""
    worst = fresh.worst(r.status for r in rows)
    if worst is None:
        return None
    lines = tuple(
        FreshLine(
            r.status.value,
            t(f"ratings.fresh.word.{r.status.value}", lang),
            _name(r, lang, agg_names),
            _scope(r, lang),
            _arrived(r, lang),
        )
        for r in rows
    )
    return FreshTable(lines, worst.value, t(f"ratings.fresh.word.{worst.value}", lang))


def read_rows(now: datetime) -> tuple[fresh.Row, ...]:
    """Источники из базы и их цвет на сегодня.

    Сутки и время прихода — в часовом поясе сервера, как на остальных экранах.
    """
    scored = read.latest_scored_periods()
    facts = {
        k: fresh.PeriodFact(*scored[k]) for k in (fresh.KIND_RS, fresh.KIND_RKO) if k in scored
    }
    aggregators = {s.aggregator: s.last_ok for s in agg_store.load_states() if s.last_ok}
    return fresh.build(
        today=now.astimezone(fresh.local_zone()).date(),
        rs=facts.get(fresh.KIND_RS),
        rko=facts.get(fresh.KIND_RKO),
        sheet_checked=read.sheet_last_checked(),
        maps_loaded=maps_store.last_ok_load(),
        aggregators=aggregators,
    )


def build(
    lang: str, agg_names: dict[str, str], *, now: datetime | None = None
) -> FreshTable | None:
    """Таблица свежести; база не ответила — `None` и след в журнале (значок скажет «нет данных»)."""
    try:
        rows = read_rows(now or datetime.now(UTC))
    except RatingsError:
        logger.warning("Свежесть источников рейтингов не прочиталась", exc_info=True)
        return None
    return lines_of(rows, lang, agg_names)
