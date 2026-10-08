"""Расчёты сводки рейтингов (D324): чистые функции над уже прочитанными фактами.

Округления здесь нет — только на экране. Решения плана: страна — среднее
пиццерий (каждая — среднее своих периодов), итог группы — среднее всех
пиццерий группы; ровно порог — в Bottom; зона риска — строго ниже порога во
всех последних N периодах.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import fmean

from .model import CATEGORY_REMARK, CATEGORY_VIOLATION, RKO, RS

TOP_LIMIT = 10
VIOLATIONS_LIMIT = 5
_COUNTED = (CATEGORY_VIOLATION, CATEGORY_REMARK)


@dataclass(frozen=True)
class Fact:
    unit: str
    unit_name: str
    country: str
    rating_type: str
    period_id: int
    begin_on: date
    score: float


@dataclass(frozen=True)
class ViolationFact:
    unit: str
    unit_name: str
    country: str
    text: str
    parent_name: str | None
    category: str
    amount: int


@dataclass(frozen=True)
class HardRule:
    rating_type: str
    match: str
    pattern: str


def unit_averages(facts: Sequence[Fact], rating_type: str) -> dict[str, float]:
    by_unit: dict[str, list[float]] = {}
    for fact in facts:
        if fact.rating_type == rating_type:
            by_unit.setdefault(fact.unit, []).append(fact.score)
    return {unit: fmean(scores) for unit, scores in by_unit.items()}


def _countries(facts: Sequence[Fact]) -> dict[str, str]:
    return {fact.unit: fact.country for fact in facts}


def group_average(
    facts: Sequence[Fact], rating_type: str, countries: Sequence[str]
) -> float | None:
    where = _countries(facts)
    values = [
        avg for unit, avg in unit_averages(facts, rating_type).items() if where[unit] in countries
    ]
    return fmean(values) if values else None


def country_average(facts: Sequence[Fact], rating_type: str, country: str) -> float | None:
    return group_average(facts, rating_type, [country])


def delta(current: float | None, previous: float | None) -> float | None:
    return None if current is None or previous is None else current - previous


@dataclass(frozen=True)
class CountryLine:
    country: str
    rs: float | None
    rko: float | None
    rs_delta: float | None
    rko_delta: float | None


def _line(
    code: str, current: Sequence[Fact], previous: Sequence[Fact], countries: Sequence[str]
) -> CountryLine:
    rs = group_average(current, RS, countries)
    rko = group_average(current, RKO, countries)
    return CountryLine(
        code,
        rs,
        rko,
        delta(rs, group_average(previous, RS, countries)),
        delta(rko, group_average(previous, RKO, countries)),
    )


def score_lines(
    current: Sequence[Fact], previous: Sequence[Fact], countries: Sequence[str]
) -> tuple[tuple[CountryLine, ...], CountryLine]:
    lines = tuple(_line(code, current, previous, [code]) for code in countries)
    return lines, _line("", current, previous, countries)


@dataclass(frozen=True)
class UnitScore:
    unit: str
    unit_name: str
    country: str
    score: float


def top_bottom(
    facts: Sequence[Fact], rating_type: str, *, threshold: float, limit: int = TOP_LIMIT
) -> tuple[tuple[UnitScore, ...], tuple[UnitScore, ...]]:
    names = {fact.unit: (fact.unit_name, fact.country) for fact in facts}
    scored = [
        UnitScore(unit, *names[unit], avg)
        for unit, avg in unit_averages(facts, rating_type).items()
    ]
    top = sorted((u for u in scored if u.score > threshold), key=lambda u: (-u.score, u.unit_name))
    bottom = sorted(
        (u for u in scored if u.score <= threshold), key=lambda u: (u.score, u.unit_name)
    )
    return tuple(top[:limit]), tuple(bottom[:limit])


@dataclass(frozen=True)
class ViolationLine:
    text: str
    count: int


@dataclass(frozen=True)
class ViolationBlock:
    """checkups == 0 сохраняется: «нет данных» отличимо от «нарушений нет»."""

    total: int
    checkups: int
    per_checkup: float | None
    top: tuple[ViolationLine, ...]


def violation_block(
    facts: Sequence[ViolationFact], *, checkups: int, limit: int = VIOLATIONS_LIMIT
) -> ViolationBlock:
    counts: Counter[str] = Counter()
    for fact in facts:
        if fact.category in _COUNTED:
            counts[fact.text] += fact.amount
    total = sum(counts.values())
    top = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return ViolationBlock(
        total,
        checkups,
        total / checkups if checkups else None,
        tuple(ViolationLine(text, n) for text, n in top),
    )


def is_hard(fact: ViolationFact, rules: Sequence[HardRule], rating_type: str) -> bool:
    text = fact.text.casefold()
    parent = (fact.parent_name or "").casefold()
    for rule in rules:
        if rule.rating_type != rating_type:
            continue
        pattern = rule.pattern.casefold()
        if rule.match == "text" and text == pattern:
            return True
        if rule.match == "contains" and (pattern in text or pattern in parent):
            return True
    return False


def hard_lines(
    facts: Sequence[ViolationFact], rules: Sequence[HardRule], rating_type: str
) -> tuple[ViolationFact, ...]:
    hard = (fact for fact in facts if is_hard(fact, rules, rating_type))
    return tuple(sorted(hard, key=lambda fact: (fact.country, fact.unit_name, fact.text)))


@dataclass(frozen=True)
class RiskUnit:
    unit: str
    unit_name: str
    country: str
    rating_type: str
    scores: tuple[float, ...]


def risk_zone(
    facts: Sequence[Fact], period_ids: Sequence[int], *, rating_type: str, threshold: float
) -> tuple[RiskUnit, ...]:
    """period_ids — последние N периодов типа, старые первыми; неполное окно не судится."""
    if not period_ids:
        return ()
    by_unit: dict[str, dict[int, Fact]] = {}
    for fact in facts:
        if fact.rating_type == rating_type and fact.period_id in period_ids:
            by_unit.setdefault(fact.unit, {})[fact.period_id] = fact
    zone = []
    for unit, by_period in by_unit.items():
        if len(by_period) != len(period_ids):
            continue
        scores = tuple(by_period[pid].score for pid in period_ids)
        if all(score < threshold for score in scores):
            sample = by_period[period_ids[-1]]
            zone.append(RiskUnit(unit, sample.unit_name, sample.country, rating_type, scores))
    return tuple(sorted(zone, key=lambda u: (u.country, u.unit_name)))
