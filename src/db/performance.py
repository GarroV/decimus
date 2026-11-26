"""Оконный кеш операционных метрик, native LFL и состояние загрузки для Swarm."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any

from src.domain.performance import NativeLfl, Observation, Window

from .reading import reading
from .source_units import with_registry

_UPSERT = """
insert into dodois.performance_windows
(country, subject_id, metric, period_from, period_to, value, numerator, denominator,
 currency, timezone, source, status, covered_units, expected_units, loaded_at, reason)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,coalesce(%s,now()),%s)
on conflict (country, subject_id, metric, period_from, period_to) do update set
 value=excluded.value, numerator=excluded.numerator, denominator=excluded.denominator,
 currency=excluded.currency, timezone=excluded.timezone, source=excluded.source,
 status=excluded.status, covered_units=excluded.covered_units,
 expected_units=excluded.expected_units, loaded_at=excluded.loaded_at, reason=excluded.reason
"""
_READ = """
select country, subject_id, metric, period_from, period_to, value, numerator,
       denominator, currency, timezone, source, status, covered_units,
       expected_units, loaded_at, reason
from dodois.performance_windows
where country=any(%s) and period_from >= %s and period_to <= %s
order by country, subject_id, metric, period_from, period_to
"""
_LFL_READ = """
select country, subject_id, query_from, query_to, granularity, bucket_date,
       revenue_raw, orders_raw, loaded_at, source
from dodois.performance_lfl where country=any(%s) and query_from=%s and query_to=%s
order by country, subject_id, granularity, bucket_date
"""


def upsert_observations(rows: Sequence[Observation]) -> int:
    """Атомарно заменить точные ключи; соседние и исторические окна сохраняются."""
    data = [
        (
            r.country,
            r.subject_id,
            r.metric,
            r.period.start,
            r.period.end,
            r.value,
            r.numerator,
            r.denominator,
            r.currency,
            r.timezone,
            r.source,
            r.status,
            r.covered_units,
            r.expected_units,
            r.loaded_at,
            r.reason,
        )
        for r in rows
    ]
    if not data:
        return 0
    with reading("кеш операционных показателей") as conn, conn.transaction(), conn.cursor() as cur:
        cur.executemany(_UPSERT, data)
    return len(data)


def read_observations(countries: Sequence[str], start: date, end: date) -> list[Observation]:
    with reading("операционные показатели") as conn:
        rows = conn.execute(_READ, (list(countries), start, end)).fetchall()
    return [Observation(r[0], r[1], r[2], Window(r[3], r[4]), *r[5:]) for r in rows]


def replace_lfl(country: str, query: Window, granularity: str, rows: Sequence[NativeLfl]) -> int:
    """Заменить ответ native LFL целиком, включая корректный пустой ответ."""
    if any(r.country != country or r.query != query or r.granularity != granularity for r in rows):
        raise ValueError("native LFL outside requested scope")
    if not re.fullmatch(r"[A-Z]{2}", country) or granularity not in {"Day", "Week", "Month"}:
        raise ValueError("invalid native LFL scope")
    data = [
        (
            r.country,
            r.subject_id,
            r.query.start,
            r.query.end,
            r.granularity,
            r.date,
            r.revenue_raw,
            r.orders_raw,
            r.source,
            r.loaded_at,
        )
        for r in rows
    ]
    with reading("кеш native LFL") as conn, conn.transaction():
        conn.execute(
            "delete from dodois.performance_lfl where country=%s and query_from=%s "
            "and query_to=%s and granularity=%s",
            (country, query.start, query.end, granularity),
        )
        if data:
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into dodois.performance_lfl (country,subject_id,query_from,query_to,"
                    "granularity,bucket_date,revenue_raw,orders_raw,source,loaded_at) "
                    "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,coalesce(%s,now()))",
                    data,
                )
    return len(data)


def read_lfl(countries: Sequence[str], query: Window) -> list[NativeLfl]:
    with reading("native LFL") as conn:
        rows = conn.execute(_LFL_READ, (list(countries), query.start, query.end)).fetchall()
    return [NativeLfl(r[0], r[1], Window(r[2], r[3]), *r[4:]) for r in rows]


def record_load(country: str, kind: str, period: Window, *, error_code: str | None = None) -> None:
    """Только код ошибки; ответы источника и тексты исключений сюда не попадают."""
    if error_code is not None and not re.fullmatch(r"[a-z_]{1,64}", error_code):
        raise ValueError("safe error code required")
    with reading("состояние операционной загрузки") as conn:
        conn.execute(
            "insert into dodois.performance_loads "
            "(country,kind,period_from,period_to,last_ok_at,error_code) "
            "values (%s,%s,%s,%s,case when %s::text is null then now() else null end,%s) "
            "on conflict (country,kind,period_from,period_to) do update set attempted_at=now(),"
            "last_ok_at=case when excluded.error_code is null then now() "
            "else dodois.performance_loads.last_ok_at end,error_code=excluded.error_code",
            (country, kind, period.start, period.end, error_code, error_code),
        )


def load_states(countries: Sequence[str], period: Window) -> list[dict[str, Any]]:
    with reading("состояние операционных загрузок") as conn:
        rows = conn.execute(
            "select country,kind,attempted_at,last_ok_at,error_code "
            "from dodois.performance_loads where country=any(%s) and period_from=%s "
            "and period_to=%s order by country,kind",
            (list(countries), period.start, period.end),
        ).fetchall()
    return [
        {
            "cc": r[0],
            "kind": r[1],
            "attempted_at": r[2].isoformat(),
            "last_ok_at": r[3].isoformat() if r[3] else None,
            "error_code": r[4],
        }
        for r in rows
    ]


def unit_names(countries: Sequence[str]) -> dict[str, tuple[str, str]]:
    with reading("названия операционных пиццерий") as conn:
        rows = conn.execute(
            with_registry(
                "select dodo_id,country_code,name from source_units where country_code=any(%s) "
                "order by country_code,name,dodo_id"
            ),
            (list(countries),),
        ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}
