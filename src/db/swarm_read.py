"""Чтение для API Swarm (#567, D335): рейтинги, собираемость, нарушения, проверки.

Только `select`, только параметры: каждый SQL — полный текст, строкой не
собирается (S608). Расчётов здесь нет: баллы рейтингов — как их загрузили,
процент и буква проверки — как их записал движок при завершении (принцип 2).
Сборку ответа (выравнивание по периодам, топ нарушений) делает
`src/ratings/feed.py`.

**Проверки читаются по охвату УК, суженному странами.** API отдаёт Swarm
то, что тот попросил (доступ по странам решает Swarm, D335), поэтому охват —
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
    u.name, u.country, i.inspection_date, i.kind, i.pct::float, i.grade
from inspections i
join units u on u.id = i.unit_id
where (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
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
    return _rows("нарушения рейтинга", facts_sql, scope), _rows("нарушения", counts_sql, scope)


def loaded_at(formats: Sequence[str]) -> datetime | None:
    """Время последней удачной загрузки любого из форматов, питающих ответ."""
    rows = _rows("журнал загрузок", _LOADED_AT_SQL, {"formats": list(formats)})
    return rows[0][0] if rows else None


def inspections(
    *, reach: Reach, date_from: date | None, date_to: date | None, limit: int
) -> list[InspectionRow]:
    """Принятые проверки в охвате, свежие первыми, не больше `limit`."""
    охват = _require_reach(reach)
    if not 1 <= limit <= MAX_INSPECTIONS + 1:
        raise DbError(f"Предел выдачи {limit} вне 1…{MAX_INSPECTIONS + 1}")
    params = {**охват.params(), "date_from": date_from, "date_to": date_to, "limit": limit}
    return [
        InspectionRow(str(r[0]), str(r[1]), *r[2:])
        for r in _rows("проверки для Swarm", _INSPECTIONS_SQL, params)
    ]
