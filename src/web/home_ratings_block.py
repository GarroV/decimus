"""Блок «Рейтинги» на «Главной» (D418): РС, РКО, карты и агрегаторы (D557) — по кластерам (D502).

Блок ничего не считает сам. Среднее группы (D353), движение к прошлому периоду
и оценки карт берутся теми же функциями, что у страницы «Рейтинги»:
`report.group_summary` (строки сводки `group_lines`), `maps.compare` и
`aggregators.summary.for_groups`. Период —
тот же, что выбран на «Главной», и ссылка заголовка ведёт на «Рейтинги» с тем
же периодом и срезом, поэтому числа на двух экранах совпадают.

Колонки — кластеры D502 (CEE, Турция, Кавказ, остальные) по странам охвата вошедшего;
колонка, где у него нет стран, не показывается. Выбрана одна страна — колонка
одна, её. «Всё время» у рейтингов нет: без границ периода берётся период по
умолчанию страницы «Рейтинги».

Отказ базы не роняет экран: блок говорит об отказе строкой.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.db.errors import DbError
from src.ratings import maps as rmaps
from src.ratings import report
from src.ratings.aggregators import summary as ragg

from .registry_period import Period

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MapScore:
    """Оценка группы на одной карте: средняя по отзывам и движение к концу прошлого периода."""

    provider: int
    avg: float | None
    delta: float | None
    reviews: int


@dataclass(frozen=True)
class AggCell:
    """Оценка группы на агрегаторе — в родной шкале (Wolt из 10, Glovo %, прочие из 5)."""

    code: str
    avg: float
    scale: int


@dataclass(frozen=True)
class Column:
    """Колонка блока: кластер (`key` — `CEE` / `OTHER`) или страна (`key` — её код)."""

    key: str
    is_cluster: bool
    rs: float | None
    rs_delta: float | None
    rko: float | None
    rko_delta: float | None
    maps: tuple[MapScore, ...]
    aggs: tuple[AggCell, ...] = ()


@dataclass(frozen=True)
class Block:
    """Что показывает блок. `failed` — рейтинги не прочитались; `maps_failed` и
    `aggs_failed` — только карты или агрегаторы; `aggs_later` — их оценки собраны
    позже периода (истории у агрегаторов нет)."""

    columns: tuple[Column, ...] = ()
    #: Параметры ссылки на «Рейтинги»: тот же срез и период.
    link: tuple[tuple[str, str], ...] = ()
    failed: bool = False
    maps_failed: bool = False
    aggs_failed: bool = False
    aggs_later: bool = False


def _args(period: Period, country: str) -> dict[str, str]:
    """Отбор в виде адреса «Рейтингов»: группа, значение и границы периода."""
    args: dict[str, str] = {}
    if country:
        args.update(group=report.GROUP_COUNTRY, value=country)
    if period.start and period.end:
        args.update({"from": period.start.isoformat(), "to": period.end.isoformat()})
    return args


def _maps_by_key(
    lines: Sequence[report.GroupLine], summary: report.GroupSummary, *, until: date
) -> dict[str, tuple[MapScore, ...]]:
    groups = tuple((_key(line, summary.selection), line.countries) for line in lines)
    before = summary.previous.end if summary.previous else None
    rows = rmaps.compare(groups, until=until, before=before)
    return {
        row.country: tuple(
            MapScore(provider, score.avg, score.delta, score.reviews)
            for provider, score in row.scores.items()
        )
        for row in rows
    }


def _aggs_by_key(
    lines: Sequence[report.GroupLine], selection: report.Selection, *, until: date, today: date
) -> tuple[dict[str, tuple[AggCell, ...]], bool]:
    groups = tuple((_key(line, selection), line.countries) for line in lines)
    order, rows, later = ragg.for_groups(groups, until=until, today=today)
    return {
        row.group: tuple(
            AggCell(code, row.scores[code].avg, row.scores[code].scale)
            for code in order
            if code in row.scores
        )
        for row in rows
    }, later


def _key(line: report.GroupLine, selection: report.Selection) -> str:
    return line.key or selection.value or ""


def load(*, scope: Sequence[str] | None, country: str, period: Period, today: date) -> Block:
    """Блок для страны `country` (пусто — все) в охвате `scope` (`None` — вся сеть)."""
    args = _args(period, country)
    link = tuple(args.items())
    try:
        summary = report.group_summary(args, today=today, scope=scope)
    except DbError as exc:
        log.warning("главная: рейтинги не прочитались (%s)", exc.__class__.__name__)
        return Block(link=link, failed=True)
    selection = summary.selection
    # Страна вне охвата рейтингов (не IMF) `select` подменил бы первой попавшейся:
    # чужие числа под её именем хуже пустоты.
    if country and selection.value != country:
        return Block(link=link)
    lines = tuple(line for line in summary.groups if line.countries)
    until = min(selection.period.end, today)
    try:
        maps_of = _maps_by_key(lines, summary, until=until)
        maps_failed = False
    except DbError as exc:
        log.warning("главная: оценки карт не прочитались (%s)", exc.__class__.__name__)
        maps_of, maps_failed = {}, True
    try:
        aggs_of, aggs_later = _aggs_by_key(lines, selection, until=until, today=today)
        aggs_failed = False
    except DbError as exc:
        log.warning("главная: оценки агрегаторов не прочитались (%s)", exc.__class__.__name__)
        aggs_of, aggs_later, aggs_failed = {}, False, True
    columns = tuple(
        Column(
            key=_key(line, selection),
            is_cluster=line.key is not None,
            rs=line.rs,
            rs_delta=line.rs_delta,
            rko=line.rko,
            rko_delta=line.rko_delta,
            maps=maps_of.get(_key(line, selection), ()),
            aggs=aggs_of.get(_key(line, selection), ()),
        )
        for line in lines
    )
    return Block(
        columns=columns,
        link=link,
        maps_failed=maps_failed,
        aggs_failed=aggs_failed,
        aggs_later=aggs_later,
    )
