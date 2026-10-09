"""Оценки на картах в базе (схема `maps`, миграция 0044): запись снимка и чтение.

Запись — одним заходом: филиалы обновляются, оценки дня ложатся по ключу
(филиал, карта, дата), повтор в тот же день перезаписывает тот же снимок.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg

from .config import check_environment
from .errors import RatingsError

_UPSERT_COMPANY = """
insert into maps.companies (uuid, network_uuid, network_name, name, country_code, city,
                            address, lat, lng, status_type_id, pointer_link, seen_at)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
on conflict (uuid) do update set
    network_uuid = excluded.network_uuid, network_name = excluded.network_name,
    name = excluded.name, country_code = excluded.country_code, city = excluded.city,
    address = excluded.address, lat = excluded.lat, lng = excluded.lng,
    status_type_id = excluded.status_type_id, pointer_link = excluded.pointer_link,
    seen_at = now()
"""

_UPSERT_RATING = """
insert into maps.ratings (company_uuid, provider_id, on_date, avg_rating, ratings_count)
values (%s, %s, %s, %s, %s)
on conflict (company_uuid, provider_id, on_date) do update set
    avg_rating = excluded.avg_rating, ratings_count = excluded.ratings_count, loaded_at = now()
"""


def save(
    companies: Sequence[tuple[Any, ...]], ratings: Sequence[tuple[Any, ...]]
) -> tuple[int, int]:
    """Записать филиалы и оценки; вернуть, сколько легло. Отказ базы — `RatingsError`."""
    try:
        with psycopg.connect(check_environment().dsn) as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(_UPSERT_COMPANY, companies)
                cur.executemany(_UPSERT_RATING, ratings)
    except psycopg.Error as exc:
        raise RatingsError(
            f"Оценки карт не легли: база отказала ({exc.__class__.__name__})"
        ) from exc
    return len(companies), len(ratings)


def log_load(*, ok: bool, companies: int = 0, ratings: int = 0, error: str | None = None) -> None:
    """След загрузки в журнале. Сам отказ журнала — в лог, загрузку он не отменяет."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            conn.execute(
                "insert into maps.loads (outcome, companies, ratings, error) "
                "values (%s, %s, %s, %s)",
                ("ok" if ok else "failed", companies, ratings, (error or "")[:500] or None),
            )
    except psycopg.Error as exc:
        raise RatingsError(f"Журнал загрузок карт не записался ({exc.__class__.__name__})") from exc


def last_ok_load() -> datetime | None:
    """Когда последний раз загрузка удалась (`None` — ни разу)."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            row = conn.execute("select max(at) from maps.loads where outcome = 'ok'").fetchone()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Журнал загрузок карт не прочитался ({exc.__class__.__name__})"
        ) from exc
    return row[0] if row else None


@dataclass(frozen=True)
class LatestRating:
    country_code: str
    provider_id: int
    avg_rating: float
    ratings_count: int
    on_date: date


def latest(countries: Sequence[str], *, until: date | None = None) -> tuple[LatestRating, ...]:
    """Последняя оценка каждого филиала на каждой карте по этим странам —
    на `until` включительно (не задан — на сегодня)."""
    if not countries:
        return ()
    sql = """
        select distinct on (r.company_uuid, r.provider_id)
               c.country_code, r.provider_id, r.avg_rating, r.ratings_count, r.on_date
        from maps.ratings r
        join maps.companies c on c.uuid = r.company_uuid
        where c.country_code = any(%s) and (%s::date is null or r.on_date <= %s::date)
        order by r.company_uuid, r.provider_id, r.on_date desc
    """
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute(sql, (list(countries), until, until)).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Оценки карт не прочитались ({exc.__class__.__name__})") from exc
    return tuple(LatestRating(str(r[0]), int(r[1]), float(r[2]), int(r[3]), r[4]) for r in rows)


def company_uuids() -> tuple[str, ...]:
    """Все известные филиалы — для дозагрузки истории."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute("select uuid::text from maps.companies order by uuid").fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Филиалы карт не прочитались ({exc.__class__.__name__})") from exc
    return tuple(str(r[0]) for r in rows)


def covered_days(company_uuid: str, start: date, end: date) -> int:
    """Сколько дней окна у филиала уже есть — чтобы повторная дозагрузка не
    тратила запросы на то, что уже легло."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            row = conn.execute(
                "select count(distinct on_date) from maps.ratings "
                "where company_uuid = %s and on_date between %s and %s",
                (company_uuid, start, end),
            ).fetchone()
    except psycopg.Error as exc:
        raise RatingsError(f"История карт не прочиталась ({exc.__class__.__name__})") from exc
    return int(row[0]) if row else 0


def points() -> tuple[tuple[str, float, float], ...]:
    """Филиалы с координатами: (uuid, широта, долгота)."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute(
                "select uuid::text, lat, lng from maps.companies "
                "where lat is not null and lng is not null"
            ).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Филиалы карт не прочитались ({exc.__class__.__name__})") from exc
    return tuple((str(r[0]), float(r[1]), float(r[2])) for r in rows)


def link_countries() -> tuple[str, ...]:
    """Страны, где искать пиццерии Dodo: страны филиалов и страны рейтингов."""
    sql = """
        select country_code from maps.companies where country_code is not null
        union select code from ratings.countries
    """
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute(sql).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Страны карт не прочитались ({exc.__class__.__name__})") from exc
    return tuple(str(r[0]) for r in rows)


def save_links(links: Sequence[tuple[str, str, str, int]]) -> int:
    """Заменить связи целиком одним заходом: (филиал, код пиццерии, имя, метры).
    Филиал без связи в новом наборе связь теряет — пиццерия могла переехать."""
    try:
        with psycopg.connect(check_environment().dsn) as conn, conn.transaction():
            conn.execute(
                "update maps.companies set dodo_id = null, dodo_name = null, "
                "link_distance_m = null, linked_at = null where dodo_id is not null"
            )
            with conn.cursor() as cur:
                cur.executemany(
                    "update maps.companies set dodo_id = %s, dodo_name = %s, "
                    "link_distance_m = %s, linked_at = now() where uuid = %s",
                    [(dodo, name, metres, uuid) for uuid, dodo, name, metres in links],
                )
    except psycopg.Error as exc:
        raise RatingsError(f"Связи карт не легли ({exc.__class__.__name__})") from exc
    return len(links)


def unit_scores(provider_id: int, *, until: date) -> dict[str, tuple[float, int]]:
    """Оценка каждой связанной пиццерии на карте на дату: код → (оценка, отзывов)."""
    sql = """
        select distinct on (c.dodo_id) c.dodo_id, r.avg_rating, r.ratings_count
        from maps.ratings r
        join maps.companies c on c.uuid = r.company_uuid
        where c.dodo_id is not null and r.provider_id = %s and r.on_date <= %s
          and r.ratings_count > 0
        order by c.dodo_id, r.on_date desc
    """
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute(sql, (provider_id, until)).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Оценки пиццерий на картах не прочитались ({exc.__class__.__name__})"
        ) from exc
    return {str(r[0]): (float(r[1]), int(r[2])) for r in rows}
