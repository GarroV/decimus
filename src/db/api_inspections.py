"""Итоги выездных проверок для API `/api/v1/inspections` (#567).

Отдаётся то, что движок уже записал при сливе: `pct` и `grade` (`0001`,
«Процент — только то, что вернул audit.py score»). Пересчёта здесь нет и быть
не может — блок `db` движок не импортирует (контракт в `pyproject.toml`).

Охват — вся сеть, без границы пространства: потребитель API — сервис уровня
управляющей компании (Swarm), и фильтр по странам он ставит сам (#567). В
выдачу идут проверки истории: принятые на приёмке (`finalized`, D199) и не
отклонённые (`retracted_at is null`). Ждущие приёмки — не итог: их оценку ещё
правят.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from .config import check_environment
from .errors import DbError

_SQL = """
select i.id, u.id, u.name, u.country, i.inspection_date, i.status, i.pct, i.grade,
       (select min(r.dodo_id) from ratings.units r where r.decimus_unit_id = u.id)
from inspections i
join units u on u.id = i.unit_id
where i.status = 'finalized'
  and i.retracted_at is null
  and u.country = any(%(countries)s)
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
order by i.inspection_date desc, i.pushed_at desc, i.id
limit %(limit)s
"""


@dataclass(frozen=True)
class InspectionResult:
    id: str
    unit_id: str
    unit_name: str
    country: str
    date: date
    status: str
    pct: Decimal
    grade: str
    unit_dodo_id: str | None


def inspection_results(
    *, countries: Sequence[str], date_from: date | None, date_to: date | None, limit: int
) -> tuple[InspectionResult, ...]:
    """Проверки истории в странах и датах, новые первыми; не больше `limit`."""
    params = {
        "countries": list(countries),
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute(_SQL, params).fetchall()
    except psycopg.Error as exc:
        raise DbError(f"Проверки не прочитались: база отказала ({type(exc).__name__})") from exc
    return tuple(
        InspectionResult(
            id=str(r[0]),
            unit_id=str(r[1]),
            unit_name=str(r[2]),
            country=str(r[3]),
            date=r[4],
            status=str(r[5]),
            pct=r[6],
            grade=str(r[7]),
            unit_dodo_id=r[8],
        )
        for r in rows
    )
