"""Чтение для API Swarm (#567, D387): рейтинги, собираемость, нарушения, проверки.

Только `select`, только параметры: каждый SQL — полный текст, строкой не
собирается (S608). Расчётов здесь нет: баллы рейтингов — как их загрузили,
процент и буква проверки — как их записал движок при завершении (принцип 2).
Сборку ответа (выравнивание по периодам, топ нарушений) делает
`src/ratings/feed.py`.

**Проверки читаются по охвату УК, суженному странами.** API отдаёт Swarm
то, что тот попросил (доступ по странам решает Swarm, D387), поэтому охват —
вся сеть (`tenants=None`), а страны — фильтр запроса. Условие охвата вписано
литералом, как во всех чтениях проверок (`tests/test_db_reach_static.py`).
Снятые проверки прячет построчная политика роли приложения (0010), ждущие
приёмки в историю не входят (D199): здесь только `finalized`.

Периоды рейтинга отбираются по дате начала внутри `[date_from, date_to]` — так
же, как сводка (`ratings_read.score_facts`). Проверка рейтинга относится к
периоду своего типа, в даты которого попала дата заказа или визита в UTC (P34,
как `ratings_read._RKO_FACTS`); отклонённые на приёмке фото-проверки РКО вне
счёта.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .errors import DbError
from .reach import Reach
from .reach import require_reach as _require_reach
from .reading import reading

#: Потолок выдачи проверок за один запрос: дальше — сужать период.
MAX_INSPECTIONS = 1000

_PERIODS_SQL = (
    "select id, begin_on, end_on, title_ru, title_en from ratings.periods "
    "where rating_type = %(type)s "
    "and begin_on >= coalesce(%(date_from)s::date, '-infinity'::date) "
    "and begin_on <= coalesce(%(date_to)s::date, 'infinity'::date) "
    "order by begin_on, id"
)

_SCORES_SQL = (
    "select s.unit_dodo_id, u.name, u.country_code, c.developer, s.period_id, s.score::float "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "join ratings.countries c on c.code = u.country_code "
    "where p.rating_type = %(type)s and u.country_code = any(%(countries)s) "
    "and p.id = any(%(periods)s) "
    "order by u.country_code, u.name, s.unit_dodo_id"
)

#: Проверки рейтинга по пиццерии, периоду и каналу. Канала нет — строки нет:
#: такую проверку знает только приёмка, и пиццерии у неё тоже нет.
_CHECKUP_COUNTS_SQL = (
    "select c.unit_dodo_id, u.name, u.country_code, p.id, c.channel, count(*) "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.periods p on p.rating_type = c.rating_type "
    "and c.occurred_at >= p.begin_on::timestamp at time zone 'UTC' "
    "and c.occurred_at < (p.end_on + 1)::timestamp at time zone 'UTC' "
    "where c.rating_type = %(type)s and u.country_code = any(%(countries)s) "
    "and p.id = any(%(periods)s) and c.channel is not null "
    "and c.acceptance is distinct from 'rejected' "
    "group by 1, 2, 3, 4, 5"
)

#: Сколько проверок учёл сам рейтинг Dodo IS (поле снимка) — рядом с теми,
#: что пришли выгрузками: выгрузки РС грузят не всегда.
_RATED_COUNTS_SQL = (
    "select s.unit_dodo_id, u.name, u.country_code, s.period_id, s.checkups_count "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "where s.checkups_count is not null and u.country_code = any(%(countries)s) "
    "and s.period_id = any(%(periods)s)"
)

#: Нарушения РКО — с проверок, в период по дате заказа.
_RKO_VIOLATIONS_SQL = (
    "select p.id, v.unit_dodo_id, u.name, u.country_code, v.text, v.parent_name, "
    "v.category, v.amount "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.violations v on v.rating_type = c.rating_type "
    "and v.checkup_dodo_id = c.dodo_id "
    "join ratings.periods p on p.rating_type = c.rating_type "
    "and c.occurred_at >= p.begin_on::timestamp at time zone 'UTC' "
    "and c.occurred_at < (p.end_on + 1)::timestamp at time zone 'UTC' "
    "where c.rating_type = 'rko' and u.country_code = any(%(countries)s) "
    "and p.id = any(%(periods)s) and c.acceptance is distinct from 'rejected' "
    "order by v.id"
)
_RKO_CHECKUPS_SQL = (
    "select u.country_code, p.id, count(*) "
    "from ratings.checkups c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.periods p on p.rating_type = c.rating_type "
    "and c.occurred_at >= p.begin_on::timestamp at time zone 'UTC' "
    "and c.occurred_at < (p.end_on + 1)::timestamp at time zone 'UTC' "
    "where c.rating_type = 'rko' and u.country_code = any(%(countries)s) "
    "and p.id = any(%(periods)s) and c.acceptance is distinct from 'rejected' "
    "group by 1, 2"
)
#: Собираемость базы рейтингов (D464): отчёты ресторана и доставки за неделю — это
#: проверки недели; выгрузка нарушений несёт только проверки с нарушениями, и счёт по
#: ней занизил бы знаменатель. Есть у (страны, периода) — берётся она, иначе счёт выше.
_RKO_COLLECTION_SQL = (
    "select u.country_code, c.period_id, sum(c.restaurant_reports + c.delivery_reports) "
    "from ratings.collection c join ratings.units u on u.dodo_id = c.unit_dodo_id "
    "join ratings.periods p on p.id = c.period_id "
    "where p.rating_type = 'rko' and u.country_code = any(%(countries)s) "
    "and p.id = any(%(periods)s) group by 1, 2"
)

#: Нарушения РС — замечания периода из снимка; проверок — сумма поля снимка.
_RS_VIOLATIONS_SQL = (
    "select v.period_id, v.unit_dodo_id, u.name, u.country_code, v.text, v.parent_name, "
    "v.category, v.amount "
    "from ratings.violations v join ratings.units u on u.dodo_id = v.unit_dodo_id "
    "join ratings.periods p on p.id = v.period_id "
    "where v.category = 'remark' and p.rating_type = 'rs' "
    "and u.country_code = any(%(countries)s) and p.id = any(%(periods)s) "
    "order by v.id"
)
_RS_CHECKUPS_SQL = (
    "select u.country_code, s.period_id, sum(s.checkups_count) "
    "from ratings.scores s join ratings.units u on u.dodo_id = s.unit_dodo_id "
    "join ratings.periods p on p.id = s.period_id "
    "where p.rating_type = 'rs' and u.country_code = any(%(countries)s) "
    "and p.id = any(%(periods)s) and s.checkups_count is not null "
    "group by 1, 2"
)

_LOADED_AT_SQL = (
    "select max(at) from ratings.imports where outcome = 'loaded' and format = any(%(formats)s)"
)

_INSPECTIONS_SQL = """
select
    i.id, u.id, (select min(r.dodo_id) from ratings.units r where r.decimus_unit_id = u.id),
    u.name, u.country, i.inspection_date, i.kind, i.pct::float, i.grade,
    prev.id, prev.inspection_date, prev.pct, prev.grade
from inspections i
join units u on u.id = i.unit_id
left join lateral (
    -- Предыдущая принятая проверка той же пиццерии — вне окна дат запроса, но в
    -- том же охвате: «движение к прошлой» не должно зависеть от выбранного окна.
    select p.id, p.inspection_date, p.pct::float as pct, p.grade
    from inspections p
    where p.unit_id = i.unit_id
      and p.status = 'finalized'
      and (%(tenants)s::text[] is null or p.tenant_code = any(%(tenants)s))
      and (p.inspection_date, p.pushed_at) < (i.inspection_date, i.pushed_at)
    order by p.inspection_date desc, p.pushed_at desc
    limit 1
) prev on true
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(id)s::uuid is null or i.id = %(id)s::uuid)
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
  and i.status = 'finalized'
order by i.inspection_date desc, i.pushed_at desc, i.id
limit %(limit)s
"""


@dataclass(frozen=True)
class PeriodRow:
    id: int
    begin_on: date
    end_on: date
    title_ru: str
    title_en: str


# Оценки на картах по связанным пиццериям (блок 2, D390): последняя оценка
# каждого филиала на каждой карте на дату. Только филиалы, связанные с
# пиццерией Dodo (`dodo_id`), и не исключённые как «не пиццерия» (D453) —
# ровно те, что входят в оценки стран на странице «Рейтинги».
_MAP_UNITS_SQL = """
select distinct on (c.uuid, r.provider_id)
    c.dodo_id, c.name, c.country_code, c.city, r.provider_id,
    r.avg_rating::float, r.ratings_count
from maps.ratings r
join maps.companies c on c.uuid = r.company_uuid
where c.dodo_id is not null
  and c.excluded_reason is null
  and c.country_code = any(%(countries)s)
  and r.on_date <= %(on)s
order by c.uuid, r.provider_id, r.on_date desc
"""


@dataclass(frozen=True)
class MapUnitRow:
    dodo_id: str
    name: str
    country: str
    city: str | None
    provider_id: int
    avg: float
    reviews: int


@dataclass(frozen=True)
class PreviousInspection:
    id: str
    inspection_date: date
    pct: float
    grade: str


@dataclass(frozen=True)
class InspectionRow:
    id: str
    unit_id: str
    unit_dodo_id: str | None
    unit_name: str
    country: str
    inspection_date: date
    kind: str
    pct: float
    grade: str
    #: Предыдущая принятая проверка той же пиццерии; `None` — это первая.
    previous: PreviousInspection | None = None


def _rows(что: str, sql: str, params: dict[str, Any]) -> list[tuple[Any, ...]]:
    with reading(что) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def periods(rating_type: str, *, date_from: date | None, date_to: date | None) -> list[PeriodRow]:
    """Периоды типа, начавшиеся в `[date_from, date_to]`, старые первыми."""
    params = {"type": rating_type, "date_from": date_from, "date_to": date_to}
    return [PeriodRow(int(r[0]), *r[1:]) for r in _rows("периоды рейтинга", _PERIODS_SQL, params)]


def _scope(countries: Sequence[str], period_ids: Sequence[int]) -> dict[str, Any]:
    return {"countries": list(countries), "periods": list(period_ids)}


def scores(
    rating_type: str, *, countries: Sequence[str], period_ids: Sequence[int]
) -> list[tuple[Any, ...]]:
    """`(unit, name, country, developer, period_id, score)`."""
    params = {"type": rating_type, **_scope(countries, period_ids)}
    return _rows("баллы рейтинга", _SCORES_SQL, params)


def checkup_counts(
    rating_type: str, *, countries: Sequence[str], period_ids: Sequence[int]
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Выгрузки `(unit, name, country, period_id, channel, n)`.

    И снимок `(unit, name, country, period_id, rated)`.
    """
    scope = _scope(countries, period_ids)
    by_channel = _rows("собираемость", _CHECKUP_COUNTS_SQL, {"type": rating_type, **scope})
    rated = _rows("собираемость", _RATED_COUNTS_SQL, scope)
    return by_channel, rated


def violation_facts(
    rating_type: str, *, countries: Sequence[str], period_ids: Sequence[int]
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Факты `(period_id, unit, name, country, text, parent, category, amount)`.

    И число проверок `(country, period_id, n)`.
    """
    scope = _scope(countries, period_ids)
    if rating_type == "rko":
        facts_sql, counts_sql = _RKO_VIOLATIONS_SQL, _RKO_CHECKUPS_SQL
    else:
        facts_sql, counts_sql = _RS_VIOLATIONS_SQL, _RS_CHECKUPS_SQL
    counts = _rows("нарушения", counts_sql, scope)
    if rating_type == "rko":
        collected = {(r[0], r[1]): r[2] for r in _rows("собираемость", _RKO_COLLECTION_SQL, scope)}
        counts = [r for r in counts if (r[0], r[1]) not in collected]
        counts += [(country, period, n) for (country, period), n in collected.items()]
    return _rows("нарушения рейтинга", facts_sql, scope), counts


def loaded_at(formats: Sequence[str]) -> datetime | None:
    """Время последней удачной загрузки любого из форматов, питающих ответ."""
    rows = _rows("журнал загрузок", _LOADED_AT_SQL, {"formats": list(formats)})
    return rows[0][0] if rows else None


def _inspection_row(r: Sequence[Any]) -> InspectionRow:
    previous = (
        PreviousInspection(str(r[9]), r[10], float(r[11]), str(r[12])) if r[9] is not None else None
    )
    return InspectionRow(
        id=str(r[0]),
        unit_id=str(r[1]),
        unit_dodo_id=r[2],
        unit_name=r[3],
        country=r[4],
        inspection_date=r[5],
        kind=r[6],
        pct=r[7],
        grade=r[8],
        previous=previous,
    )


def inspections(
    *, reach: Reach, date_from: date | None, date_to: date | None, limit: int
) -> list[InspectionRow]:
    """Принятые проверки в охвате, свежие первыми, не больше `limit`."""
    охват = _require_reach(reach)
    if not 1 <= limit <= MAX_INSPECTIONS + 1:
        raise DbError(f"Предел выдачи {limit} вне 1…{MAX_INSPECTIONS + 1}")
    params = {
        **охват.params(),
        "id": None,
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
    }
    return [_inspection_row(r) for r in _rows("проверки для Swarm", _INSPECTIONS_SQL, params)]


def inspection(*, reach: Reach, inspection_id: str) -> InspectionRow | None:
    """Одна принятая проверка в охвате — та же запись, что в списке; `None` — нет такой.

    `inspection_id` — уже проверенный UUID: кривой отбивает вызывающий (400),
    здесь он стал бы ошибкой базы.
    """
    охват = _require_reach(reach)
    params = {**охват.params(), "id": inspection_id, "date_from": None, "date_to": None, "limit": 1}
    rows = _rows("проверка для Swarm", _INSPECTIONS_SQL, params)
    return _inspection_row(rows[0]) if rows else None


def map_units(*, countries: Sequence[str], on: date) -> list[MapUnitRow]:
    """Последняя оценка связанных филиалов на `on` включительно, по каждой карте."""
    if not countries:
        return []
    params = {"countries": list(countries), "on": on}
    return [
        MapUnitRow(str(r[0]), str(r[1]), str(r[2]), r[3], int(r[4]), float(r[5]), int(r[6]))
        for r in _rows("оценки пиццерий на картах", _MAP_UNITS_SQL, params)
    ]


# Топ нарушений по нашим проверкам (D426): записи принятых проверок в датах и
# странах запроса, по коду пункта — сколько раз записан и в скольких проверках.
# Коды, а не формулировки (конституция): подписи — из методики той версии,
# по которой считалась самая свежая проверка охвата (`checklist_version`).
_FINDING_COUNTS_SQL = """
select u.country, f.code, count(*), count(distinct i.id)
from findings f
join inspections i on i.id = f.inspection_id
join units u on u.id = i.unit_id
where i.status = 'finalized'
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
group by u.country, f.code
"""
_INSPECTION_COUNTS_SQL = """
select u.country, count(*),
       (array_agg(i.checklist_version order by i.inspection_date desc, i.pushed_at desc))[1]
from inspections i
join units u on u.id = i.unit_id
where i.status = 'finalized'
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and i.inspection_date >= coalesce(%(date_from)s::date, '-infinity'::date)
  and i.inspection_date <= coalesce(%(date_to)s::date, 'infinity'::date)
group by u.country
"""


@dataclass(frozen=True)
class FindingCount:
    country: str
    code: str
    findings: int
    inspections: int


@dataclass(frozen=True)
class CountryInspections:
    country: str
    inspections: int
    checklist_version: str


def finding_counts(
    *, reach: Reach, date_from: date | None, date_to: date | None
) -> tuple[list[FindingCount], list[CountryInspections]]:
    """Сколько раз записан каждый пункт по странам и сколько проверок в стране."""
    охват = _require_reach(reach)
    params = {**охват.params(), "date_from": date_from, "date_to": date_to}
    counts = [
        FindingCount(str(r[0]), str(r[1]), int(r[2]), int(r[3]))
        for r in _rows("нарушения проверок для Swarm", _FINDING_COUNTS_SQL, params)
    ]
    totals = [
        CountryInspections(str(r[0]), int(r[1]), str(r[2] or ""))
        for r in _rows("число проверок для Swarm", _INSPECTION_COUNTS_SQL, params)
    ]
    return counts, totals
