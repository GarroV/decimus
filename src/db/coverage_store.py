"""Что лежит в базе по каждой паре «страна × источник» данных рейтингов (D704, D706, #1444).

Читает счётчики для проверки покрытия (`src/health/coverage_check.py`); решений здесь нет,
пороги и страны приходят параметрами.

**База страны** — работающие пиццерии реестра `agg.units`, у которых в `unit_profiles` стадия
`open` или `paused` либо профиля нет вовсе, без тестовых (то же правило, что
`agg_store.is_test_unit`) и без исключённых стран.
Поверх неё по каждому источнику считается: у скольких пиццерий данные есть (`ever`), у скольких
свежие или входят в последний период (`covered`), и дата самых новых данных.

Источники: РС и РКО — `ratings.scores` ⋈ `ratings.periods`, у каждой страны свой последний
период с оценками; клиентские оценки — `dodois.unit_kr_month` за два месяца (с ненулевым
числом оценок), подключение страны — `dodois.logins`; карты — `maps.ratings` по привязке
`maps.companies.dodo_id` (не исключённые); агрегаторы — `agg.points` с `dodo_id` (не
исключённые) ⋈ `agg.ratings`, без пиццерий, отмеченных в `agg.unit_absent` или перечисленных
в `src/domain/coverage_exempt.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

import psycopg

from . import agg_store
from .config import check_environment
from .errors import DbError
from .pool import connection

#: База страны: пиццерии, у которых вообще ждём данные.
_BASE = """
    select u.dodo_id, u.country_code, u.name
    from agg.units u
    left join unit_profiles p on p.dodo_id = u.dodo_id
    where u.working
      and u.name !~* ('^\\s*(' || %(test_pattern)s || ')\\s*$')
      and (p.dodo_id is null or p.stage in ('open', 'paused'))
      and u.country_code <> all(%(excluded)s)
"""

#: Пиццерии, которых на площадке агрегатора нет: отметки людей (`agg.unit_absent`) и список
#: «не обслуживается» (`src/domain/coverage_exempt.py`, пары приходят параметрами). Из базы
#: страны для этого агрегатора они вычитаются и в долю не входят.
_GONE = """
    gone as (
        select a.aggregator, a.dodo_id from agg.unit_absent a
        union
        select x.src, b.dodo_id
        from base b
        join unnest(%(ex_src)s::text[], %(ex_name)s::text[]) as x(src, nm)
          on btrim(b.name) = x.nm
    )
"""


@dataclass(frozen=True)
class Counts:
    """Счётчики одной пары: у скольких пиццерий данные есть и годны, и дата самых новых."""

    ever: int
    covered: int
    latest: date | None


@dataclass(frozen=True)
class Raw:
    """Всё прочитанное для проверки; ключи — код страны (и источника/агрегатора)."""

    base: dict[str, int] = field(default_factory=dict)
    periods: dict[tuple[str, str], Counts] = field(default_factory=dict)  # (РС/РКО, страна)
    kr: dict[tuple[str, date], int] = field(default_factory=dict)  # (страна, месяц) → пиццерий
    kr_logins: frozenset[str] = frozenset()
    maps: dict[tuple[int, str], Counts] = field(default_factory=dict)  # (провайдер, страна)
    aggs: dict[tuple[str, str], Counts] = field(default_factory=dict)  # (агрегатор, страна)
    agg_absent: dict[tuple[str, str], int] = field(default_factory=dict)
    agg_points: frozenset[tuple[str, str]] = frozenset()  # (агрегатор, страна) с точками


def _fail(what: str, exc: psycopg.Error) -> DbError:
    return DbError(f"{what}: база отказала ({exc.__class__.__name__})")


_BASE_COUNT = f"with base as ({_BASE}) select country_code, count(*) from base group by 1"  # noqa: S608

_PERIODS = f"""
    with base as ({_BASE}),
    per as (
        select b.country_code, p.rating_type, p.end_on, count(distinct b.dodo_id) as n
        from base b
        join ratings.scores s on s.unit_dodo_id = b.dodo_id
        join ratings.periods p on p.id = s.period_id
        group by 1, 2, 3
    )
    select distinct on (country_code, rating_type) country_code, rating_type, end_on, n
    from per order by country_code, rating_type, end_on desc
"""  # noqa: S608

_KR = f"""
    with base as ({_BASE})
    select b.country_code, k.month, count(distinct b.dodo_id)
    from base b join dodois.unit_kr_month k on k.dodo_id = b.dodo_id
    where k.month = any(%(months)s) and k.dine_in_count + k.delivery_count > 0
    group by 1, 2
"""  # noqa: S608

_MAPS = f"""
    with base as ({_BASE})
    select r.provider_id, b.country_code,
           count(distinct b.dodo_id) as ever,
           count(distinct b.dodo_id) filter (where r.on_date >= %(since)s) as fresh,
           max(r.on_date)
    from base b
    join maps.companies c on c.dodo_id = b.dodo_id and c.excluded_reason is null
    join maps.ratings r on r.company_uuid = c.uuid and r.provider_id = any(%(providers)s)
    group by 1, 2
"""  # noqa: S608

_AGGS = f"""
    with base as ({_BASE}), {_GONE}
    select p.aggregator, b.country_code,
           count(distinct b.dodo_id) as ever,
           count(distinct b.dodo_id) filter (where r.on_date >= %(since)s) as fresh,
           max(r.on_date)
    from base b
    join agg.points p on p.dodo_id = b.dodo_id and p.excluded_reason is null
    join agg.ratings r on r.aggregator = p.aggregator and r.point_key = p.point_key
    where not exists (
        select 1 from gone g where g.aggregator = p.aggregator and g.dodo_id = b.dodo_id
    )
    group by 1, 2
"""  # noqa: S608

_ABSENT = f"""
    with base as ({_BASE}), {_GONE}
    select g.aggregator, b.country_code, count(distinct b.dodo_id)
    from gone g join base b on b.dodo_id = g.dodo_id
    group by 1, 2
"""  # noqa: S608


def read(
    *,
    excluded: Sequence[str],
    months: Sequence[date],
    since: date,
    providers: Sequence[int],
    unit_exempt: Sequence[tuple[str, str]] = (),
) -> Raw:
    """Счётчики по всем источникам. `months` — месяцы клиентских оценок (первые числа),
    `since` — самая ранняя дата, ещё считающаяся свежей у карт и агрегаторов,
    `providers` — коды карт Pointer, `unit_exempt` — пары (агрегатор, имя пиццерии), которых на
    площадке нет. Отказ базы — `DbError`."""
    params = {
        "excluded": list(excluded),
        "months": list(months),
        "since": since,
        "providers": list(providers),
        "test_pattern": agg_store.TEST_UNIT_PATTERN,
        "ex_src": [src for src, _ in unit_exempt],
        "ex_name": [name for _, name in unit_exempt],
    }
    try:
        with connection(check_environment().dsn) as conn:
            base = {str(r[0]): int(r[1]) for r in conn.execute(_BASE_COUNT, params)}
            # Последний период у каждой страны: покрытие — доля пиццерий с оценкой в нём.
            periods = {
                (str(r[1]), str(r[0])): Counts(int(r[3]), int(r[3]), r[2])
                for r in conn.execute(_PERIODS, params)
            }
            kr = {(str(r[0]), r[1]): int(r[2]) for r in conn.execute(_KR, params)}
            logins = frozenset(str(r[0]) for r in conn.execute("select country from dodois.logins"))
            maps = {
                (int(r[0]), str(r[1])): Counts(int(r[2]), int(r[3]), r[4])
                for r in conn.execute(_MAPS, params)
            }
            aggs = {
                (str(r[0]), str(r[1])): Counts(int(r[2]), int(r[3]), r[4])
                for r in conn.execute(_AGGS, params)
            }
            absent = {(str(r[0]), str(r[1])): int(r[2]) for r in conn.execute(_ABSENT, params)}
            points = frozenset(
                (str(r[0]), str(r[1]))
                for r in conn.execute("select distinct aggregator, country_code from agg.points")
            )
    except psycopg.Error as exc:
        raise _fail("Покрытие данных рейтингов не прочиталось", exc) from exc
    return Raw(base, periods, kr, logins, maps, aggs, absent, points)
