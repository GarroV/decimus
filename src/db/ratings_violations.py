"""D746: scoped source rows for ratings violations, without writes or photo claims.

RS source-period identity takes precedence over the calendar date of a checkup.
RKO checkup violations retain the existing order-date selection; period remarks
belong to the source period. Unknown explicit identifiers never fall back to dates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from src.ratings.model import RKO, RS
from src.ratings.periods import KIND_RATING, ReportPeriod

from .config import check_environment
from .errors import RatingsError
from .pool import connection
from .request_memo import memoized


@dataclass(frozen=True)
class Occurrence:
    row_id: int
    kind: str
    unit: str
    unit_name: str
    country: str
    text: str
    parent: str | None
    category: str
    criterion_id: str | None
    amount: int
    checkup_id: str | None
    occurred_at: datetime | None
    source_period_id: str | None
    loaded_at: datetime


@dataclass(frozen=True)
class CheckupCoverage:
    count: int
    loaded_at: datetime | None


_FACTS = """
with scope as (
    select %s::text kind, %s::text[] countries, %s::date begin_on,
           %s::date end_on, %s::bigint period_id
)
select v.id, v.rating_type, u.dodo_id, u.name, u.country_code, v.text,
       v.parent_name, v.category, v.criterion_id, v.amount,
       c.dodo_id, c.occurred_at, coalesce(c.period_dodo_id, vp.dodo_id), i.at
from ratings.violations v
join ratings.units u on u.dodo_id = v.unit_dodo_id
join ratings.imports i on i.id = v.import_id
cross join scope s
left join ratings.checkups c
  on c.rating_type = v.rating_type and c.dodo_id = v.checkup_dodo_id
left join ratings.periods vp
  on vp.id = v.period_id and vp.rating_type = v.rating_type
left join ratings.periods cp
  on cp.dodo_id = c.period_dodo_id and cp.rating_type = c.rating_type
where v.rating_type = s.kind and u.country_code = any(s.countries)
  and v.category in ('violation', 'remark')
  and (v.checkup_dodo_id is null or c.unit_dodo_id = v.unit_dodo_id)
  and c.acceptance is distinct from 'rejected'
  and case
    when v.period_id is not null then
      (s.period_id is null and vp.end_on >= s.begin_on and vp.begin_on <= s.end_on)
      or vp.id = s.period_id
    when v.rating_type = 'rs' and c.period_dodo_id is not null then
      (s.period_id is null and cp.end_on >= s.begin_on and cp.begin_on <= s.end_on)
      or cp.id = s.period_id
    else c.occurred_at >= s.begin_on::timestamp at time zone 'UTC'
      and c.occurred_at < (s.end_on + 1)::timestamp at time zone 'UTC'
  end
order by v.id
"""

_CHECKUPS = """
with scope as (
    select %s::text kind, %s::text[] countries, %s::date begin_on,
           %s::date end_on, %s::bigint period_id
)
select count(*), max(i.at)
from ratings.checkups c
join ratings.units u on u.dodo_id = c.unit_dodo_id
join ratings.imports i on i.id = c.import_id
cross join scope s
left join ratings.periods p
  on p.dodo_id = c.period_dodo_id and p.rating_type = c.rating_type
where c.rating_type = s.kind and u.country_code = any(s.countries)
  and c.acceptance is distinct from 'rejected'
  and case when c.rating_type = 'rs' and c.period_dodo_id is not null then
    (s.period_id is null and p.end_on >= s.begin_on and p.begin_on <= s.end_on)
    or p.id = s.period_id
  else c.occurred_at >= s.begin_on::timestamp at time zone 'UTC'
    and c.occurred_at < (s.end_on + 1)::timestamp at time zone 'UTC'
  end
"""


def facts(kind: str, countries: Sequence[str], period: ReportPeriod) -> tuple[Occurrence, ...]:
    """Countable source violations; empty countries always means an empty scope."""
    params = _scope(kind, countries, period)
    if not params[1]:
        return ()
    key = ("ratings.violations", kind, tuple(params[1]), period.begin, period.end, params[4])
    return memoized(key, lambda: tuple(Occurrence(*row) for row in _query(_FACTS, params)))


def checkup_coverage(kind: str, countries: Sequence[str], period: ReportPeriod) -> CheckupCoverage:
    """Known metadata checks; this does NOT establish a complete violations export."""
    params = _scope(kind, countries, period)
    if not params[1]:
        return CheckupCoverage(0, None)
    key = ("ratings.violation_checks", kind, tuple(params[1]), period.begin, period.end, params[4])
    return memoized(key, lambda: CheckupCoverage(*_query(_CHECKUPS, params)[0]))


def _scope(
    kind: str, countries: Sequence[str], period: ReportPeriod
) -> tuple[str, list[str], date, date, int | None]:
    if kind not in (RS, RKO):
        raise ValueError("Unsupported rating type")
    codes = tuple(sorted(set(countries)))
    if any(len(c) != 2 or not c.isascii() or not c.isalpha() or c != c.upper() for c in codes):
        raise ValueError("Invalid country code")
    if period.end < period.begin:
        raise ValueError("Invalid period")
    period_id = None
    if kind == RS and period.kind == KIND_RATING:
        raw = period.key.removeprefix("rs:")
        if not period.key.startswith("rs:") or not raw.isascii() or not raw.isdigit():
            raise ValueError("Invalid source period")
        period_id = int(raw)
    return (kind, list(codes), period.begin, period.end, period_id)


def _query(sql: str, params: Sequence[Any]) -> list[tuple[Any, ...]]:
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, params).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Нарушения рейтингов не прочитались ({type(exc).__name__})") from exc
    return rows
