"""Месячная история принятых проверок: вся история охвата без лимита реестра.

Проценты читаются сохранёнными, включая legacy; оценки не пересчитываются.
Снятые проверки скрывает RLS, черновики исключаются явно.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .reach import Reach, require_reach
from .reading import reading


@dataclass(frozen=True)
class Month:
    """Месяц, число проверок и сумма сохранённых процентов."""

    start: date
    count: int
    total: float


_SQL = """
select date_trunc('month', i.inspection_date)::date, count(*), sum(i.pct)
from inspections i join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(selected)s::text[] is null or u.country = any(%(selected)s))
  and i.status = 'finalized'
  and i.inspection_date <= %(today)s
group by 1 order by 1
"""


def months(*, reach: Reach, countries: tuple[str, ...] | None, today: date) -> tuple[Month, ...]:
    """Месяцы выбранных стран внутри обязательного охвата; пустой срез — пусто."""
    scope = require_reach(reach)
    with reading("история проверок") as conn, conn.cursor() as cur:
        cur.execute(
            _SQL,
            {
                **scope.params(),
                "selected": None if countries is None else list(countries),
                "today": today,
            },
        )
        return tuple(Month(row[0], int(row[1]), float(row[2])) for row in cur.fetchall())
