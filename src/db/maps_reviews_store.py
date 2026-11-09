"""Оценки на картах поштучно (схема `maps`, миграция 0127): запись, ход загрузки, чтение.

Месяц оценки — `published_at` (D733): дата, когда её поставили. Удалённая оценка остаётся
строкой с `is_deleted`, в расчёт не идёт. Текст отзыва не хранится.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from .config import check_environment
from .errors import RatingsError
from .pool import connection

_UPSERT_REVIEW = """
insert into maps.reviews (id, company_uuid, provider_id, rating, published_at, is_deleted,
                          updated_at)
values (%s, %s, %s, %s, %s, %s, now())
on conflict (id) do update set
    rating = excluded.rating, published_at = excluded.published_at,
    is_deleted = excluded.is_deleted, updated_at = now()
where (maps.reviews.rating, maps.reviews.published_at, maps.reviews.is_deleted)
      is distinct from (excluded.rating, excluded.published_at, excluded.is_deleted)
"""

# Оценка, которой не оказалось в свежей выгрузке за её окно, — исчезла у Pointer: считаем удалённой.
_MARK_MISSING = """
update maps.reviews set is_deleted = true, updated_at = now()
where company_uuid = %s and provider_id = %s and published_at between %s and %s
  and not is_deleted and id <> all(%s)
"""

_TOUCH_SYNC = """
insert into maps.reviews_sync (company_uuid, provider_id, backfilled_from, topped_up_on)
values (%s, %s, %s, %s)
on conflict (company_uuid, provider_id) do update set
    backfilled_from = case when %s::boolean
        then least(maps.reviews_sync.backfilled_from, excluded.backfilled_from)
        else maps.reviews_sync.backfilled_from end,
    topped_up_on = excluded.topped_up_on
"""


@dataclass(frozen=True)
class SyncState:
    """Что по паре (филиал, карта) уже загружено."""

    company_uuid: str
    provider_id: int
    backfilled_from: date | None
    topped_up_on: date | None


def sync_states(providers: Sequence[int]) -> tuple[SyncState, ...]:
    """Все пары «связанный филиал × карта набора» с ходом их загрузки (пустой — не грузили)."""
    sql = """
        select c.uuid::text, p.id, s.backfilled_from, s.topped_up_on
        from maps.companies c
        cross join unnest(%s::int[]) as p(id)
        left join maps.reviews_sync s on s.company_uuid = c.uuid and s.provider_id = p.id
        where c.dodo_id is not null and c.excluded_reason is null
        order by c.uuid, p.id
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, (list(providers),)).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(
            f"Ход загрузки оценок карт не прочитался ({exc.__class__.__name__})"
        ) from exc
    return tuple(SyncState(str(r[0]), int(r[1]), r[2], r[3]) for r in rows)


def save_reviews(
    rows: Sequence[tuple[str, str, int, int, date, bool]],
    *,
    company_uuid: str,
    provider_id: int,
    start: date,
    end: date,
    today: date,
    backfill: bool,
) -> int:
    """Записать оценки пары за окно `start..end` и отметить пару загруженной.

    `rows` — `(id, филиал, карта, звёзды, дата, удалена)`. Оценки окна, которых нет в выгрузке,
    помечаются удалёнными. `backfill` — окно открывает историю (`backfilled_from`). Одна
    транзакция: падение посреди окна не оставляет пару «загруженной». Возвращает число строк."""
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(_UPSERT_REVIEW, rows)
                cur.execute(
                    _MARK_MISSING, (company_uuid, provider_id, start, end, [r[0] for r in rows])
                )
                cur.execute(_TOUCH_SYNC, (company_uuid, provider_id, start, today, backfill))
    except psycopg.Error as exc:
        raise RatingsError(
            f"Оценки карт не легли: база отказала ({exc.__class__.__name__})"
        ) from exc
    return len(rows)


@dataclass(frozen=True)
class MonthlyStats:
    """Оценки провайдера по пиццериям и месяцам; `floor` — первый месяц загруженной истории."""

    by_unit: dict[str, dict[date, tuple[int, Decimal]]]  # код → месяц → (оценок, сумма звёзд)
    floor: date | None


def monthly_stats(provider_id: int, *, until: date) -> MonthlyStats:
    """Число и сумма неудалённых оценок по пиццериям и месяцам публикации, до даты включительно.

    Филиалы одной пиццерии складываются. `floor` — месяц начала самой короткой загрузки
    истории среди пар карты (нет загруженной пары — `None`, значений нет)."""
    sql = """
        select c.dodo_id, date_trunc('month', r.published_at)::date, count(*), sum(r.rating)
        from maps.reviews r
        join maps.companies c on c.uuid = r.company_uuid
        where r.provider_id = %s and not r.is_deleted and r.published_at <= %s
          and c.dodo_id is not null and c.excluded_reason is null
        group by 1, 2
    """
    floor_sql = (
        "select date_trunc('month', max(backfilled_from))::date from maps.reviews_sync "
        "where provider_id = %s and backfilled_from is not null"
    )
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, (provider_id, until)).fetchall()
            floor = conn.execute(floor_sql, (provider_id,)).fetchone()
    except psycopg.Error as exc:
        raise RatingsError(f"Оценки карт не прочитались ({exc.__class__.__name__})") from exc
    by_unit: dict[str, dict[date, tuple[int, Decimal]]] = defaultdict(dict)
    for unit, month, count, total in rows:
        by_unit[str(unit)][month] = (int(count), Decimal(total))
    return MonthlyStats(dict(by_unit), floor[0] if floor else None)


@dataclass(frozen=True)
class CardCounts:
    """Сверка карточки: оценок в выгрузке против прироста счётчика карточки за то же время."""

    company_uuid: str
    provider_id: int
    since: date  # с какой даты загружена история
    ours: int  # неудалённых оценок в `maps.reviews` с этой даты
    counter_now: int  # счётчик карточки в последнем снимке
    counter_before: (
        int | None
    )  # счётчик на последний снимок до `since`; нет снимка — сравнить нечем


def card_counts(providers: Sequence[int]) -> tuple[CardCounts, ...]:
    """Данные сверки по каждой загруженной паре (филиал, карта)."""
    sql = """
        select s.company_uuid::text, s.provider_id, s.backfilled_from,
               (select count(*) from maps.reviews r
                 where r.company_uuid = s.company_uuid and r.provider_id = s.provider_id
                   and not r.is_deleted and r.published_at >= s.backfilled_from),
               (select r.ratings_count from maps.ratings r
                 where r.company_uuid = s.company_uuid and r.provider_id = s.provider_id
                 order by r.on_date desc limit 1),
               (select r.ratings_count from maps.ratings r
                 where r.company_uuid = s.company_uuid and r.provider_id = s.provider_id
                   and r.on_date < s.backfilled_from
                 order by r.on_date desc limit 1)
        from maps.reviews_sync s
        join maps.companies c on c.uuid = s.company_uuid
        where s.provider_id = any(%s) and s.backfilled_from is not null
          and c.dodo_id is not null and c.excluded_reason is null
        order by s.company_uuid, s.provider_id
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, (list(providers),)).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Сверка оценок карт не прочиталась ({exc.__class__.__name__})") from exc
    return tuple(
        CardCounts(
            str(r[0]),
            int(r[1]),
            r[2],
            int(r[3]),
            int(r[4] or 0),
            None if r[5] is None else int(r[5]),
        )
        for r in rows
    )
