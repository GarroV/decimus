"""Блок «Рейтинги» на «Главной» (D418): РС, РКО, карты и агрегаторы (D557) — по кластерам (D502).

Блок ничего не считает сам. Среднее группы (D353), движение к прошлому периоду
и оценки карт берутся теми же функциями, что у страницы «Рейтинги»:
`report.group_summary` (строки сводки `group_lines`), `maps.compare` и
`aggregators.summary.for_groups`. Период —
тот же, что выбран на «Главной», и ссылка заголовка ведёт на «Рейтинги» с тем
же периодом и срезом, поэтому числа на двух экранах совпадают.

Колонки по срезу экрана (D583, D584): без среза — кластеры D502 (CEE, Турция, Кавказ,
остальные) по странам охвата вошедшего, колонка без стран не показывается; выбран
кластер — итог кластера и по колонке на каждую его страну; выбрана страна — итог
страны и по колонке на каждую её пиццерию в порядке «Сортировки» экрана. Строки —
РС, РКО, по строке на карту и на агрегатор: подписи стоят на месте, колонки
прокручиваются вбок. «Всё время» у рейтингов нет: без границ периода берётся период
по умолчанию страницы «Рейтинги».

Отказ базы не роняет экран: блок говорит об отказе строкой.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from statistics import fmean

from src.db import agg_store, maps_store
from src.db.errors import DbError
from src.ratings import maps as rmaps
from src.ratings import report
from src.ratings.aggregators import summary as ragg
from src.ratings.model import RKO, RS
from src.ratings.summary import Fact, delta, unit_averages

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
    """Колонка блока: кластер (`key` — `CEE` / `OTHER`), страна (`key` — её код) или
    пиццерия (`key` — её код Dodo, `unit` — название). `is_total` — итог выбранного
    среза: первая колонка при выбранном кластере или стране."""

    key: str
    is_cluster: bool
    rs: float | None
    rs_delta: float | None
    rko: float | None
    rko_delta: float | None
    maps: tuple[MapScore, ...]
    aggs: tuple[AggCell, ...] = ()
    unit: str = ""
    is_total: bool = False

    def map_of(self, provider: int) -> MapScore | None:
        return next((m for m in self.maps if m.provider == provider), None)

    def agg_of(self, code: str) -> AggCell | None:
        return next((a for a in self.aggs if a.code == code), None)


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

    @property
    def map_providers(self) -> tuple[int, ...]:
        """Карты, по которым есть строка: по порядку первого появления в колонках."""
        return tuple(dict.fromkeys(m.provider for c in self.columns for m in c.maps))

    @property
    def agg_codes(self) -> tuple[str, ...]:
        """Агрегаторы, у которых есть оценка хоть в одной колонке."""
        return tuple(dict.fromkeys(a.code for c in self.columns for a in c.aggs))


#: Ключ итоговой колонки в группах карт и агрегаторов: код кластера («TR») совпал бы с кодом страны.
TOTAL = "*"

Groups = Sequence[tuple[str, Sequence[str]]]
Facts = tuple[Sequence[Fact], Sequence[Fact]]


def _args(period: Period, *, country: str, cluster: str) -> dict[str, str]:
    """Отбор в виде адреса «Рейтингов»: группа, значение и границы периода."""
    args: dict[str, str] = {}
    if country:
        args.update(group=report.GROUP_COUNTRY, value=country)
    elif cluster:
        args.update(group=report.GROUP_CLUSTER, value=cluster)
    if period.start and period.end:
        args.update({"from": period.start.isoformat(), "to": period.end.isoformat()})
    return args


def _maps_by_key(
    groups: Groups, summary: report.GroupSummary, *, until: date
) -> dict[str, tuple[MapScore, ...]]:
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
    groups: Groups, *, until: date, today: date
) -> tuple[dict[str, tuple[AggCell, ...]], bool]:
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


def _column(
    key: str, line: report.GroupLine, *, is_cluster: bool = False, is_total: bool = False
) -> Column:
    return Column(
        key=key,
        is_cluster=is_cluster,
        rs=line.rs,
        rs_delta=line.rs_delta,
        rko=line.rko,
        rko_delta=line.rko_delta,
        maps=(),
        is_total=is_total,
    )


def _country_lines(
    codes: Sequence[str], selection: report.Selection, facts: Facts
) -> dict[str, report.GroupLine]:
    """Строка сводки на каждую страну — той же `group_lines`, что итог кластера."""
    one = report.Selection(report.GROUP_COUNTRY, None, selection.period)
    empty = report.Choices((), (), ())
    return {code: report.group_lines(one, empty, (code,), facts)[0] for code in codes}


def _with(column: Column, maps: tuple[MapScore, ...], aggs: tuple[AggCell, ...]) -> Column:
    return replace(column, maps=maps, aggs=aggs)


# ── Пиццерии выбранной страны (D584) ────────────────────────────────────────


def _unit_order(sort: str, inspected: Mapping[str, date]) -> Callable[[Column], tuple[object, ...]]:
    """Порядок колонок-пиццерий — тот же код «Сортировки», что у таблицы «Пиццерии».

    `score` — худшая РС первой, пиццерия без РС в конце; `delta` — по движению РС;
    `date` — по дате последней проверки (без проверки — в конце); `unit` — по названию.
    """

    def key(c: Column) -> tuple[object, ...]:
        name = c.unit.lower()
        if sort == "unit":
            return (name, c.key)
        if sort == "date":
            when = inspected.get(c.key)
            return (when is None, -(when.toordinal() if when else 0), name)
        if sort == "delta":
            return (c.rs_delta is None, c.rs_delta or 0.0, name)
        return (c.rs is None, c.rs if c.rs is not None else 0.0, name)

    return key


def _unit_columns(facts: Facts, *, sort: str, inspected: Mapping[str, date]) -> tuple[Column, ...]:
    current, previous = facts
    names = {f.unit: f.unit_name for f in (*previous, *current)}
    now = {k: unit_averages(current, k) for k in (RS, RKO)}
    was = {k: unit_averages(previous, k) for k in (RS, RKO)}

    def value(kind: str, unit: str) -> tuple[float | None, float | None]:
        a, b = now[kind].get(unit), was[kind].get(unit)
        return a, delta(a, b)

    columns = []
    for unit, name in names.items():
        rs, rs_delta = value(RS, unit)
        rko, rko_delta = value(RKO, unit)
        columns.append(Column(unit, False, rs, rs_delta, rko, rko_delta, (), unit=name))
    return tuple(sorted(columns, key=_unit_order(sort, inspected)))


def _unit_maps(
    units: Sequence[str], *, until: date, before: date | None
) -> dict[str, tuple[MapScore, ...]]:
    scores: dict[str, list[MapScore]] = {u: [] for u in units}
    for provider in rmaps.SHOWN_PROVIDERS:
        now = maps_store.unit_scores(provider, until=until)
        was = maps_store.unit_scores(provider, until=before) if before else {}
        for unit in units:
            got, old = now.get(unit), was.get(unit)
            avg = round(got[0], 2) if got else None
            delta = round(got[0] - old[0], 2) if got and old else None
            scores[unit].append(MapScore(provider, avg, delta, got[1] if got else 0))
    return {u: tuple(v) for u, v in scores.items()}


def _unit_aggs(
    units: Sequence[str], country: str, *, until: date, today: date
) -> dict[str, tuple[AggCell, ...]]:
    rows = agg_store.latest((country,), until=until)
    if not rows and until < today:
        rows = agg_store.latest((country,))
    order = ragg.aggregators_of(rows)
    found: dict[tuple[str, str], list[agg_store.LatestRating]] = {}
    for row in rows:
        found.setdefault((row.dodo_id, row.aggregator), []).append(row)
    return {
        unit: tuple(
            AggCell(code, fmean(r.score for r in got), got[0].scale)
            for code in order
            if (got := found.get((unit, code)))
        )
        for unit in units
    }


def load(
    *,
    scope: Sequence[str] | None,
    country: str,
    cluster: str = "",
    period: Period,
    today: date,
    sort: str = "score",
    inspected: Mapping[str, date] | None = None,
) -> Block:
    """Блок для среза экрана: страна `country` (пусто — все), иначе кластер `cluster`,
    в охвате `scope` (`None` — вся сеть). `sort` и `inspected` (код пиццерии → дата
    последней проверки) задают порядок колонок-пиццерий выбранной страны."""
    args = _args(period, country=country, cluster=cluster)
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
    if not lines:
        return Block(link=link)
    until = min(selection.period.end, today)
    before = summary.previous.end if summary.previous else None
    units: tuple[str, ...] = ()
    if country or cluster:
        try:
            facts = report.period_facts(lines[0].countries, selection.period, summary.previous)
        except DbError as exc:
            log.warning("главная: рейтинги не прочитались (%s)", exc.__class__.__name__)
            return Block(link=link, failed=True)
        total = (
            lines[0].countries,
            _column(TOTAL, lines[0], is_cluster=not country, is_total=True),
        )
        groups: list[tuple[str, Sequence[str]]] = [(TOTAL, total[0])]
        if country:
            columns = (total[1], *_unit_columns(facts, sort=sort, inspected=inspected or {}))
            units = tuple(c.key for c in columns[1:])
        else:
            per = _country_lines(lines[0].countries, selection, facts)
            columns = (total[1], *(_column(code, line) for code, line in per.items()))
            groups += [(code, (code,)) for code in per]
    else:
        columns = tuple(
            _column(_key(line, selection), line, is_cluster=line.key is not None) for line in lines
        )
        groups = [(_key(line, selection), line.countries) for line in lines]
    try:
        maps_of = _maps_by_key(groups, summary, until=until)
        if units:
            maps_of.update(_unit_maps(units, until=until, before=before))
        maps_failed = False
    except DbError as exc:
        log.warning("главная: оценки карт не прочитались (%s)", exc.__class__.__name__)
        maps_of, maps_failed = {}, True
    try:
        aggs_of, aggs_later = _aggs_by_key(groups, until=until, today=today)
        if units:
            aggs_of.update(_unit_aggs(units, country, until=until, today=today))
        aggs_failed = False
    except DbError as exc:
        log.warning("главная: оценки агрегаторов не прочитались (%s)", exc.__class__.__name__)
        aggs_of, aggs_later, aggs_failed = {}, False, True
    return Block(
        columns=tuple(_with(c, maps_of.get(c.key, ()), aggs_of.get(c.key, ())) for c in columns),
        link=link,
        maps_failed=maps_failed,
        aggs_failed=aggs_failed,
        aggs_later=aggs_later,
    )
