"""D746 violation analytics: one case denominator and the same scoped drilldown.

Legacy rows without a criterion id receive an explicit text-derived identity;
they are not silently linked to a known criterion or translated into its code.
The source schema has no photos. Checkup links are rebuilt from identifiers.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from src.db import ratings_violations as read
from src.db.ratings_violations import Occurrence

from .links import checkup_rating_url, hex_id, unit_rating_url
from .model import CATEGORY_REMARK, CATEGORY_VIOLATION, RKO, RS
from .periods import KIND_RATING, ReportPeriod
from .summary import normalize_text


@dataclass(frozen=True)
class ViolationRow:
    key: str
    criterion_id: str | None
    identity: str
    text: str
    parent: str | None
    category: str
    cases: int
    units: int
    share: float
    previous_cases: int | None
    delta: int | None
    delta_pct: float | None


@dataclass(frozen=True)
class SourceCheck:
    id: str
    url: str
    occurred_at: datetime | None
    cases: int


@dataclass(frozen=True)
class UnitViolations:
    unit: str
    name: str
    country: str
    cases: int
    rating_url: str
    checks: tuple[SourceCheck, ...]


@dataclass(frozen=True)
class ViolationDetail:
    row: ViolationRow
    units: tuple[UnitViolations, ...]
    photos_available: bool = False


@dataclass(frozen=True)
class CountryViolations:
    code: str
    cases: int
    units: int
    rows: tuple[ViolationRow, ...]


@dataclass(frozen=True)
class ViolationView:
    kind: str
    period: ReportPeriod
    previous: ReportPeriod | None
    total_cases: int
    units: int
    rows: tuple[ViolationRow, ...]
    countries: tuple[CountryViolations, ...]
    selected: ViolationDetail | None
    loaded_at: datetime | None
    source: str = "ratings_exports"
    photos_available: bool = False
    observed_checkups: int = 0
    checkups_loaded_at: datetime | None = None

    @property
    def top(self) -> tuple[ViolationRow, ...]:
        return self.rows[:5]

    @property
    def has_data(self) -> bool:
        """Only observed source violations prove coverage; missing rows are not a clean audit."""
        return bool(self.rows)

    @property
    def coverage(self) -> str:
        """Checks-only metadata must never look like a proven zero violations result."""
        return "violations" if self.rows else "checks_only" if self.observed_checkups else "unknown"


def identity(fact: Occurrence) -> str:
    if fact.criterion_id:
        return f"{fact.kind}:criterion:{fact.criterion_id}"
    payload = "\x00".join((normalize_text(fact.text), normalize_text(fact.parent or "")))
    return f"{fact.kind}:legacy:{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _scoped(
    kind: str, countries: Sequence[str], facts: Sequence[Occurrence]
) -> tuple[Occurrence, ...]:
    allowed = set(countries)
    return tuple(
        f
        for f in facts
        if f.kind == kind
        and f.country in allowed
        and f.category in (CATEGORY_VIOLATION, CATEGORY_REMARK)
        and f.amount > 0
    )


def _grouped(facts: Sequence[Occurrence]) -> dict[str, list[Occurrence]]:
    groups: dict[str, list[Occurrence]] = {}
    for fact in facts:
        groups.setdefault(identity(fact), []).append(fact)
    return groups


def _rows(
    current: Sequence[Occurrence], before: Sequence[Occurrence] | None
) -> tuple[ViolationRow, ...]:
    groups = _grouped(current)
    previous = _grouped(before or ())
    total = sum(f.amount for f in current)
    result = []
    for key, facts in groups.items():
        names: Counter[str] = Counter()
        for fact in facts:
            names[fact.text] += fact.amount
        text = min(names, key=lambda value: (-names[value], normalize_text(value), value))
        exemplar = min((f for f in facts if f.text == text), key=lambda f: f.row_id)
        count = sum(f.amount for f in facts)
        was = None if before is None else sum(f.amount for f in previous.get(key, ()))
        result.append(
            ViolationRow(
                key,
                exemplar.criterion_id,
                "criterion" if exemplar.criterion_id else "legacy_text",
                text,
                exemplar.parent,
                exemplar.category,
                count,
                len({f.unit for f in facts}),
                100 * count / total,
                was,
                None if was is None else count - was,
                100 * (count - was) / was if was else None,
            )
        )
    return tuple(sorted(result, key=lambda row: (-row.cases, normalize_text(row.text), row.key)))


def _detail(kind: str, row: ViolationRow, facts: Sequence[Occurrence]) -> ViolationDetail:
    groups: dict[str, list[Occurrence]] = {}
    for fact in facts:
        if identity(fact) == row.key:
            groups.setdefault(fact.unit, []).append(fact)
    units = []
    for unit, group in groups.items():
        first = min(group, key=lambda f: f.row_id)
        checks: dict[str, list[Occurrence]] = {}
        for fact in group:
            if checkup := hex_id(fact.checkup_id):
                checks.setdefault(checkup, []).append(fact)
        links = []
        for checkup, rows in sorted(checks.items()):
            source = rows[0]
            links.append(
                SourceCheck(
                    checkup,
                    checkup_rating_url(unit, kind, checkup, hex_id(source.source_period_id)),
                    source.occurred_at,
                    sum(f.amount for f in rows),
                )
            )
        units.append(
            UnitViolations(
                unit,
                first.unit_name,
                first.country,
                sum(f.amount for f in group),
                unit_rating_url(unit, kind),
                tuple(links),
            )
        )
    return ViolationDetail(row, tuple(sorted(units, key=lambda u: (-u.cases, u.name, u.unit))))


def assemble(
    kind: str,
    countries: Sequence[str],
    period: ReportPeriod,
    facts: Sequence[Occurrence],
    *,
    previous: ReportPeriod | None = None,
    before: Sequence[Occurrence] = (),
    criterion: str | None = None,
    observed_checkups: int = 0,
    checkups_loaded_at: datetime | None = None,
) -> ViolationView:
    """Pure assembly; shares are percentages of cases, never percentages of checks."""
    if kind not in (RS, RKO):
        raise ValueError("Unsupported rating type")
    current = _scoped(kind, countries, facts)
    past = _scoped(kind, countries, before) if previous is not None else ()
    # An empty export does not establish that the previous window was clean.
    baseline = past if past else None
    rows = _rows(current, baseline)
    by_country = tuple(
        CountryViolations(
            code,
            sum(f.amount for f in current if f.country == code),
            len({f.unit for f in current if f.country == code}),
            _rows(
                tuple(f for f in current if f.country == code),
                tuple(f for f in past if f.country == code) or None,
            ),
        )
        for code in sorted({f.country for f in current})
    )
    chosen = next((r for r in rows if r.key == criterion), None)
    return ViolationView(
        kind,
        period,
        previous,
        sum(f.amount for f in current),
        len({f.unit for f in current}),
        rows,
        by_country,
        _detail(kind, chosen, current) if chosen is not None else None,
        max((f.loaded_at for f in current), default=None),
        observed_checkups=observed_checkups,
        checkups_loaded_at=checkups_loaded_at,
    )


def _window(kind: str, period: ReportPeriod) -> read.Window:
    source_id = None
    if kind == RS and period.kind == KIND_RATING:
        raw = period.key.removeprefix("rs:")
        if not period.key.startswith("rs:") or not raw.isascii() or not raw.isdigit():
            raise ValueError("Invalid source period")
        source_id = int(raw)
    return read.Window(period.begin, period.end, source_id)


def build(
    kind: str,
    countries: Sequence[str],
    period: ReportPeriod,
    *,
    previous: ReportPeriod | None = None,
    criterion: str | None = None,
) -> ViolationView:
    """Load only the requested scope; provenance belongs to violation exports, not API scores."""
    current = read.facts(kind, countries, _window(kind, period))
    before = read.facts(kind, countries, _window(kind, previous)) if previous is not None else ()
    checks = read.checkup_coverage(kind, countries, _window(kind, period))
    return assemble(
        kind,
        countries,
        period,
        current,
        previous=previous,
        before=before,
        criterion=criterion,
        observed_checkups=checks.count,
        checkups_loaded_at=checks.loaded_at,
    )
