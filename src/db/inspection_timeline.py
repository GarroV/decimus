"""История принятых проверок по датам и месяцам, без лимита реестра.

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


#: Сколько проверок одного дня несёт точка графика для подсказки; остальные считаются, не читаются.
DAY_ITEMS = 8


@dataclass(frozen=True)
class Item:
    """Одна проверка дня: для подсказки на графике (пиццерия, страна, вид, результат, ссылка)."""

    id: str
    unit: str
    country: str
    kind: str
    pct: float


@dataclass(frozen=True)
class Day:
    """Дата обхода, число проверок, сумма сохранённых процентов и первые проверки дня."""

    start: date
    count: int
    total: float
    items: tuple[Item, ...] = ()


_DAYS_SQL = """
select i.inspection_date, count(*), sum(i.pct),
  (array_agg(jsonb_build_object('id', i.id::text, 'unit', u.name, 'country', u.country,
                                'kind', i.kind, 'pct', i.pct) order by u.name, i.id))[1:%(items)s]
from inspections i join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(selected)s::text[] is null or u.country = any(%(selected)s))
  and i.status = 'finalized'
  and i.inspection_date <= %(today)s
group by 1 order by 1
"""


def days(*, reach: Reach, countries: tuple[str, ...] | None, today: date) -> tuple[Day, ...]:
    """Точные даты всех принятых проверок; несколько в один день — одна средняя точка.

    К точке — первые `DAY_ITEMS` проверок дня для подсказки, тем же запросом.
    """
    scope = require_reach(reach)
    with reading("динамика проверок") as conn, conn.cursor() as cur:
        cur.execute(
            _DAYS_SQL,
            {
                **scope.params(),
                "selected": None if countries is None else list(countries),
                "today": today,
                "items": DAY_ITEMS,
            },
        )
        return tuple(
            Day(
                row[0],
                int(row[1]),
                float(row[2]),
                tuple(
                    Item(str(x["id"]), x["unit"], x["country"], x["kind"], float(x["pct"]))
                    for x in row[3]
                ),
            )
            for row in cur.fetchall()
        )
