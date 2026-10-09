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


def latest(countries: Sequence[str]) -> tuple[LatestRating, ...]:
    """Последняя оценка каждого филиала на каждой карте по этим странам."""
    if not countries:
        return ()
    sql = """
        select distinct on (r.company_uuid, r.provider_id)
               c.country_code, r.provider_id, r.avg_rating, r.ratings_count, r.on_date
        from maps.ratings r
        join maps.companies c on c.uuid = r.company_uuid
        where c.country_code = any(%s)
        order by r.company_uuid, r.provider_id, r.on_date desc
    """
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            rows = conn.execute(sql, (list(countries),)).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Оценки карт не прочитались ({exc.__class__.__name__})") from exc
    return tuple(LatestRating(str(r[0]), int(r[1]), float(r[2]), int(r[3]), r[4]) for r in rows)
