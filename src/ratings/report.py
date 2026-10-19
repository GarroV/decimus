"""Сводка раздела «Рейтинги» (D324): отбор → чтение → расчёты `summary`.

Не чистый модуль: ходит в базу дверью `src.db.ratings_read`. Расчёты — в
`summary`, периоды — в `periods`; здесь только сборка. Готовых строк для экрана
здесь нет (язык — параметр): страны и периоды уходят с названиями на обоих
языках, как лежат в данных.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from src.db import ratings_read as read
from src.db.ratings_read import CountryRow

from .model import RKO, RS
from .periods import (
    RatingPeriod,
    ReportPeriod,
    default_period,
    parse_period,
    previous_period,
    range_period,
)
from .summary import (
    CountryLine,
    Fact,
    HardRule,
    Point,
    RiskUnit,
    UnitScore,
    ViolationBlock,
    ViolationFact,
    delta,
    group_average,
    hard_lines,
    points,
    risk_zone,
    score_lines,
    top_bottom,
    violation_block,
)

GROUP_IMF = "imf"
GROUP_DEVELOPER = "developer"
GROUP_COUNTRY = "country"
GROUP_CLUSTER = "cluster"
GROUPS = (GROUP_IMF, GROUP_CLUSTER, GROUP_DEVELOPER, GROUP_COUNTRY)
#: Кластеры IMF (D502, вместо двух D384): CEE — Европа, TR — Турция, CAUCASUS —
#: Кавказ, OTHER — остальные страны. Порядок — порядок колонок и выбора.
CLUSTERS = ("CEE", "TR", "CAUCASUS", "OTHER")
#: Сколько месяцев на графике свечей — по конец выбранного периода.


LEVEL_CLUSTER = "cluster"
LEVEL_SLICE = "slice"
LEVEL_COUNTRY = "country"


@dataclass(frozen=True)
class GroupLine:
    """Строка сводки по группе (`level`): `cluster` — кластер в срезе IMF,
    `slice` — весь выбранный срез (`key` — None), `country` — страна среза
    девелопера (D385). Срез кластера и страны — одной строкой (D383)."""

    key: str | None
    countries: tuple[str, ...]
    rs: float | None
    rs_delta: float | None
    rko: float | None
    rko_delta: float | None
    rs_points: tuple[Point, ...]
    rko_points: tuple[Point, ...]
    level: str = LEVEL_SLICE


@dataclass(frozen=True)
class Selection:
    group: str
    value: str | None
    period: ReportPeriod


@dataclass(frozen=True)
class Choices:
    developers: tuple[str, ...]
    countries: tuple[CountryRow, ...]
    rs_periods: tuple[RatingPeriod, ...]


@dataclass(frozen=True)
class Summary:
    selection: Selection
    countries: tuple[str, ...]
    groups: tuple[GroupLine, ...]
    lines: tuple[CountryLine, ...]
    total: CountryLine
    previous: ReportPeriod | None
    rko_cluster: ViolationBlock
    rko_by_country: dict[str, ViolationBlock]
    rs_cluster: ViolationBlock
    rs_by_country: dict[str, ViolationBlock]
    rs_top: tuple[UnitScore, ...]
    rs_bottom: tuple[UnitScore, ...]
    rs_hard: tuple[ViolationFact, ...]
    rko_top: tuple[UnitScore, ...]
    rko_bottom: tuple[UnitScore, ...]
    rko_hard: tuple[ViolationFact, ...]
    risk: tuple[RiskUnit, ...]
    #: Типы рейтинга, у которых периодов меньше окна зоны риска (P37): «никого»
    #: про них не говорится — их не судили.
    risk_short: tuple[str, ...]
    thresholds: dict[str, float]
    last_loaded: dict[str, datetime]


def choices(only: Collection[str] | None = None) -> Choices:
    """Что можно выбрать: только страны охвата IMF (D318) и их девелоперы.
    `only` — сузить до этих стран (охват партнёра в MCP); `None` — без сужения,
    как на экране: рейтинги видят все (D327)."""
    imf = tuple(
        row for row in read.countries() if row.is_imf and (only is None or row.code in only)
    )
    developers = tuple(sorted({row.developer for row in imf if row.developer}))
    return Choices(developers, imf, tuple(RatingPeriod(*p) for p in read.rs_periods()))


def _value(group: str, wanted: str | None, found: Choices) -> str | None:
    if group == GROUP_DEVELOPER:
        if wanted in found.developers:
            return wanted
        return found.developers[0] if found.developers else None
    if group == GROUP_CLUSTER:
        return wanted if wanted in CLUSTERS else CLUSTERS[0]
    if group == GROUP_COUNTRY:
        codes = tuple(row.code for row in found.countries)
        if wanted in codes:
            return wanted
        return codes[0] if codes else None
    return None


def select(
    args: Mapping[str, str], *, today: date, only: Collection[str] | None = None
) -> tuple[Selection, Choices]:
    """Отбор из адреса страницы; незнакомое значение заменяется первым допустимым."""
    found = choices(only)
    group = args.get("group", "")
    group = group if group in GROUPS else GROUP_IMF
    value = _value(group, args.get("value") or None, found)
    latest = found.rs_periods[0].begin_on if found.rs_periods else None
    period = (
        _dates(args, found.rs_periods)
        or parse_period(args.get("period", ""), rs_periods=found.rs_periods)
        or default_period(latest, today=today)
    )
    return Selection(group, value, period), found


def _dates(args: Mapping[str, str], rs_periods: Sequence[RatingPeriod]) -> ReportPeriod | None:
    """Период из календаря «с — по» (`from`, `to`); нет обеих дат — нет периода."""
    try:
        begin = date.fromisoformat((args.get("from") or "").strip())
        end = date.fromisoformat((args.get("to") or "").strip())
    except ValueError:
        return None
    return range_period(begin, end, rs_periods=rs_periods)


def group_countries(selection: Selection, countries: Sequence[CountryRow]) -> tuple[str, ...]:
    if selection.group == GROUP_COUNTRY:
        return tuple(row.code for row in countries if row.code == selection.value)
    if selection.group == GROUP_DEVELOPER:
        return tuple(
            row.code for row in countries if row.developer and row.developer == selection.value
        )
    if selection.group == GROUP_CLUSTER:
        return tuple(row.code for row in countries if row.cluster == selection.value)
    return tuple(row.code for row in countries)


def _facts(rows: Sequence[tuple[object, ...]]) -> list[Fact]:
    return [Fact(*row) for row in rows]  # type: ignore[arg-type]


def _vfacts(rows: Sequence[tuple[object, ...]]) -> list[ViolationFact]:
    return [ViolationFact(*row) for row in rows]  # type: ignore[arg-type]


def _blocks(
    facts: Sequence[ViolationFact], counts: Mapping[str, int], countries: Sequence[str]
) -> tuple[ViolationBlock, dict[str, ViolationBlock]]:
    cluster = violation_block(facts, checkups=sum(counts.values()))
    by_country = {
        code: violation_block([f for f in facts if f.country == code], checkups=counts.get(code, 0))
        for code in countries
    }
    return cluster, by_country


def _risk(
    codes: Sequence[str], period: ReportPeriod, limits: Mapping[str, float]
) -> tuple[tuple[RiskUnit, ...], tuple[str, ...]]:
    """Зона риска — по полному окну из `risk_periods` (P11): меньше периодов — не судим,
    и тип уходит вторым значением, чтобы экран не выдал «не судили» за «никого» (P37)."""
    window = int(limits["risk_periods"])
    risk: list[RiskUnit] = []
    short: list[str] = []
    for rating_type in (RS, RKO):
        ids = read.last_period_ids(rating_type, until=period.end, n=window)
        if len(ids) < window:
            short.append(rating_type)
            continue
        facts = _facts(
            read.score_facts(countries=codes, begin=period.begin, end=period.end, period_ids=ids)
        )
        risk += risk_zone(facts, ids, rating_type=rating_type, threshold=limits["risk_threshold"])
    return tuple(risk), tuple(short)


def group_lines(
    selection: Selection,
    found: Choices,
    codes: Sequence[str],
    facts: tuple[Sequence[Fact], Sequence[Fact]],
) -> tuple[GroupLine, ...]:
    """В срезе IMF — строка на кластер; у девелопера — общая строка и строка на
    каждую его страну (D385); в остальных — одна строка среза.
    `facts` — (текущий период, прошлый); точки графика — из текущего (D396)."""
    current, previous = facts
    parts: list[tuple[str, str | None, tuple[str, ...]]]
    if selection.group == GROUP_IMF:
        parts = [
            (
                LEVEL_CLUSTER,
                key,
                tuple(r.code for r in found.countries if r.cluster == key and r.code in codes),
            )
            for key in CLUSTERS
        ]
        # Кластер без стран в охвате строкой не идёт: четыре кластера (D502) у
        # партнёра одной страны дали бы три пустые строки.
        parts = [part for part in parts if part[2]]
    else:
        parts = [(LEVEL_SLICE, None, tuple(codes))]
        if selection.group == GROUP_DEVELOPER and len(codes) > 1:
            parts += [(LEVEL_COUNTRY, code, (code,)) for code in codes]
    out = []
    for level, key, part in parts:
        values = {k: group_average(current, k, part) for k in (RS, RKO)}
        before = {k: group_average(previous, k, part) for k in (RS, RKO)}
        out.append(
            GroupLine(
                key=key,
                countries=part,
                rs=values[RS],
                rs_delta=delta(values[RS], before[RS]),
                rko=values[RKO],
                rko_delta=delta(values[RKO], before[RKO]),
                rs_points=points(current, RS, part),
                rko_points=points(current, RKO, part),
                level=level,
            )
        )
    return tuple(out)


def period_scores(selection: Selection, codes: Sequence[str]) -> list[Fact]:
    """Оценки пиццерий этих стран за периоды рейтинга, задевшие выбранный период."""
    period = selection.period
    return _facts(read.score_facts(countries=codes, begin=period.begin, end=period.end))


def period_facts(
    codes: Sequence[str], period: ReportPeriod, prev: ReportPeriod | None
) -> tuple[list[Fact], list[Fact]]:
    """Факты периода и прошлого периода — общий вход `build` и `group_summary`."""
    current = _facts(read.score_facts(countries=codes, begin=period.begin, end=period.end))
    previous = (
        _facts(read.score_facts(countries=codes, begin=prev.begin, end=prev.end)) if prev else []
    )
    return current, previous


@dataclass(frozen=True)
class GroupSummary:
    """Только строки сводки по группам: для экранов, которым нужна сводка, а не весь отчёт."""

    selection: Selection
    groups: tuple[GroupLine, ...]
    previous: ReportPeriod | None


def group_summary(
    args: Mapping[str, str], *, today: date, scope: Sequence[str] | None = None
) -> GroupSummary:
    """Строки сводки по группам для отбора из `args` — те же, что даёт `build`.

    Отбор и период читаются так же, как на экране «Рейтинги» (`select`), а числа
    считает та же `group_lines`: экран, который показывает сводку рядом, не
    считает её сам и не расходится с «Рейтингами». `scope` сужает страны группы
    до охвата вошедшего (`None` — без сужения).
    """
    selection, found = select(args, today=today)
    codes = group_countries(selection, found.countries)
    if scope is not None:
        codes = tuple(code for code in codes if code in scope)
    prev = previous_period(selection.period, rs_periods=found.rs_periods)
    facts = period_facts(codes, selection.period, prev)
    return GroupSummary(selection, group_lines(selection, found, codes, facts), prev)


def build_groups(
    selection: Selection, found: Choices
) -> tuple[tuple[GroupLine, ...], ReportPeriod | None]:
    """Только строки сводки по группам и прошлый период — без нарушений, Top/Bottom
    и зоны риска. Считает тем же `group_lines`, что и `build`."""
    codes = group_countries(selection, found.countries)
    prev = previous_period(selection.period, rs_periods=found.rs_periods)
    facts = period_facts(codes, selection.period, prev)
    return group_lines(selection, found, codes, facts), prev


def build(selection: Selection) -> Summary:
    found = choices()
    codes = group_countries(selection, found.countries)
    period = selection.period
    prev = previous_period(period, rs_periods=found.rs_periods)
    current, previous = period_facts(codes, period, prev)
    lines, total = score_lines(current, previous, codes)
    groups = group_lines(selection, found, codes, (current, previous))
    limits = read.settings()
    rules = [HardRule(r[1], r[2], r[3]) for r in read.hard_rules()]
    rko_rows, rko_counts = read.rko_violation_facts(
        countries=codes, begin=period.begin, end=period.end
    )
    rs_rows, rs_counts = read.rs_remark_facts(countries=codes, begin=period.begin, end=period.end)
    rko_facts, rs_facts = _vfacts(rko_rows), _vfacts(rs_rows)
    rko_cluster, rko_by = _blocks(rko_facts, rko_counts, codes)
    rs_cluster, rs_by = _blocks(rs_facts, rs_counts, codes)
    top = limits["top_threshold"]
    rs_top, rs_bottom = top_bottom(current, RS, threshold=top, previous=previous)
    rko_top, rko_bottom = top_bottom(current, RKO, threshold=top, previous=previous)
    risk, risk_short = _risk(codes, period, limits)
    return Summary(
        selection=selection,
        countries=codes,
        groups=groups,
        lines=lines,
        total=total,
        previous=prev,
        rko_cluster=rko_cluster,
        rko_by_country=rko_by,
        rs_cluster=rs_cluster,
        rs_by_country=rs_by,
        rs_top=rs_top,
        rs_bottom=rs_bottom,
        rs_hard=hard_lines(rs_facts, rules, RS),
        rko_top=rko_top,
        rko_bottom=rko_bottom,
        rko_hard=hard_lines(rko_facts, rules, RKO),
        risk=risk,
        risk_short=risk_short,
        thresholds=limits,
        last_loaded=read.last_loaded(),
    )
