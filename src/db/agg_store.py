"""Оценки в агрегаторах доставки в базе (схема `agg`, миграция 0050).

Запись — одним заходом на агрегатор: точки обновляются, оценки дня ложатся по
ключу (агрегатор, точка, дата), повтор в тот же день перезаписывает тот же
снимок. Отметку «не пиццерия» (`excluded_reason`) запись не трогает — она
ставится руками и переживает сбор, как у карт.

Реестр пиццерий (`agg.units`, миграция 0051, D424) — то, что бот прочитал из
публичного API Dodo: по нему видно, где какая пиццерия, и новые находятся сами.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

import psycopg
from psycopg.types.json import Jsonb

from src.ratings.maps_link import DodoUnit

from .config import check_environment
from .errors import RatingsError
from .pool import connection


@dataclass(frozen=True)
class PointRow:
    aggregator: str
    point_key: str
    country_code: str
    name: str | None
    url: str | None
    lat: float | None
    lng: float | None
    dodo_id: str | None
    dodo_name: str | None
    link_distance_m: int | None
    extra: dict[str, object]


@dataclass(frozen=True)
class RatingRow:
    aggregator: str
    point_key: str
    on_date: date
    score: float
    scale: int
    votes: int | None
    votes_exact: bool
    is_open: bool | None


_UPSERT_POINT = """
insert into agg.points (aggregator, point_key, country_code, name, url, lat, lng,
                        dodo_id, dodo_name, link_distance_m, extra, seen_at)
values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
on conflict (aggregator, point_key) do update set
    country_code = excluded.country_code, name = excluded.name, url = excluded.url,
    lat = coalesce(excluded.lat, agg.points.lat), lng = coalesce(excluded.lng, agg.points.lng),
    dodo_id = excluded.dodo_id, dodo_name = excluded.dodo_name,
    link_distance_m = excluded.link_distance_m,
    extra = agg.points.extra || excluded.extra, seen_at = now()
"""

_UPSERT_RATING = """
insert into agg.ratings (aggregator, point_key, on_date, score, scale, votes, votes_exact, is_open)
values (%s, %s, %s, %s, %s, %s, %s, %s)
on conflict (aggregator, point_key, on_date) do update set
    score = excluded.score, scale = excluded.scale, votes = excluded.votes,
    votes_exact = excluded.votes_exact, is_open = excluded.is_open, loaded_at = now()
"""


def _fail(what: str, exc: psycopg.Error) -> RatingsError:
    return RatingsError(f"{what}: база отказала ({exc.__class__.__name__})")


def save(points: Sequence[PointRow], ratings: Sequence[RatingRow]) -> tuple[int, int]:
    """Записать точки и оценки; вернуть, сколько легло. Отказ базы — `RatingsError`."""
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    _UPSERT_POINT,
                    [
                        (
                            p.aggregator,
                            p.point_key,
                            p.country_code,
                            p.name,
                            p.url,
                            p.lat,
                            p.lng,
                            p.dodo_id,
                            p.dodo_name,
                            p.link_distance_m,
                            Jsonb(p.extra),
                        )
                        for p in points
                    ],
                )
                cur.executemany(
                    _UPSERT_RATING,
                    [
                        (
                            r.aggregator,
                            r.point_key,
                            r.on_date,
                            r.score,
                            r.scale,
                            r.votes,
                            r.votes_exact,
                            r.is_open,
                        )
                        for r in ratings
                    ],
                )
    except psycopg.Error as exc:
        raise _fail("Оценки агрегаторов не легли", exc) from exc
    return len(points), len(ratings)


def log_load(
    aggregator: str, *, ok: bool, points: int = 0, ratings: int = 0, error: str | None = None
) -> None:
    """След сбора агрегатора в журнале."""
    try:
        with connection(check_environment().dsn) as conn:
            conn.execute(
                "insert into agg.loads (aggregator, outcome, points, ratings, error) "
                "values (%s, %s, %s, %s, %s)",
                (
                    aggregator,
                    "ok" if ok else "failed",
                    points,
                    ratings,
                    (error or "")[:500] or None,
                ),
            )
    except psycopg.Error as exc:
        raise _fail("Журнал сбора агрегаторов не записался", exc) from exc


def last_run() -> datetime | None:
    """Когда последний раз шёл сбор — удачный или нет (`None` — ни разу).
    Неудачный агрегатор пробуется снова на следующие сутки, а не каждый час:
    иначе один сломанный агрегатор гонял бы весь сбор по кругу."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute("select max(at) from agg.loads").fetchone()
    except psycopg.Error as exc:
        raise _fail("Журнал сбора агрегаторов не прочитался", exc) from exc
    return row[0] if row else None


def last_ok_points(aggregator: str) -> int:
    """Сколько точек принёс последний удачный сбор агрегатора (0 — ни разу)."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute(
                "select points from agg.loads where aggregator = %s and outcome = 'ok' "
                "order by at desc limit 1",
                (aggregator,),
            ).fetchone()
    except psycopg.Error as exc:
        raise _fail("Журнал сбора агрегаторов не прочитался", exc) from exc
    return int(row[0]) if row else 0


def known_points(aggregator: str) -> tuple[PointRow, ...]:
    """Точки агрегатора из справочника — для сборщиков «по известной точке»."""
    sql = """
        select aggregator, point_key, country_code, name, url, lat, lng, dodo_id, dodo_name,
               link_distance_m, extra
        from agg.points where aggregator = %s and excluded_reason is null
        order by point_key
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, (aggregator,)).fetchall()
    except psycopg.Error as exc:
        raise _fail("Точки агрегатора не прочитались", exc) from exc
    return tuple(
        PointRow(
            str(r[0]),
            str(r[1]),
            str(r[2]),
            r[3],
            r[4],
            r[5],
            r[6],
            r[7],
            r[8],
            r[9],
            dict(r[10] or {}),
        )
        for r in rows
    )


@dataclass(frozen=True)
class LatestRating:
    country_code: str
    aggregator: str
    dodo_id: str
    score: float
    scale: int
    votes: int | None
    on_date: date


def latest(countries: Sequence[str], *, until: date | None = None) -> tuple[LatestRating, ...]:
    """Последняя оценка каждой привязанной к пиццерии точки по этим странам — на
    `until` включительно (не задан — на сегодня)."""
    if not countries:
        return ()
    sql = """
        select distinct on (r.aggregator, r.point_key)
               p.country_code, r.aggregator, p.dodo_id, r.score, r.scale, r.votes, r.on_date
        from agg.ratings r
        join agg.points p on p.aggregator = r.aggregator and p.point_key = r.point_key
        where p.country_code = any(%s) and p.dodo_id is not null and p.excluded_reason is null
          and (%s::date is null or r.on_date <= %s::date)
        order by r.aggregator, r.point_key, r.on_date desc
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, (list(countries), until, until)).fetchall()
    except psycopg.Error as exc:
        raise _fail("Оценки агрегаторов не прочитались", exc) from exc
    return tuple(
        LatestRating(
            str(r[0]),
            str(r[1]),
            str(r[2]),
            float(r[3]),
            int(r[4]),
            None if r[5] is None else int(r[5]),
            r[6],
        )
        for r in rows
    )


@dataclass(frozen=True)
class LoadState:
    aggregator: str
    at: datetime
    outcome: str
    points: int
    error: str | None
    last_ok: datetime | None


def load_states() -> tuple[LoadState, ...]:
    """Последний сбор каждого агрегатора и когда он последний раз удался."""
    sql = """
        select distinct on (l.aggregator) l.aggregator, l.at, l.outcome, l.points, l.error,
               (select max(o.at) from agg.loads o
                where o.aggregator = l.aggregator and o.outcome = 'ok')
        from agg.loads l
        order by l.aggregator, l.at desc
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql).fetchall()
    except psycopg.Error as exc:
        raise _fail("Журнал сбора агрегаторов не прочитался", exc) from exc
    return tuple(LoadState(str(r[0]), r[1], str(r[2]), int(r[3]), r[4], r[5]) for r in rows)


@dataclass(frozen=True)
class UpdateRequest:
    """Заявка на обновление вне расписания (миграция 0053). `aggregators` — какие
    собрать; пусто — все, что бот собирает сам. `done_at is None` — в очереди."""

    id: int
    requested_at: datetime
    requested_by: str
    aggregators: tuple[str, ...]
    done_at: datetime | None
    outcome: str | None
    error: str | None


def _request(row: tuple[object, ...]) -> UpdateRequest:
    return UpdateRequest(
        int(row[0]),  # type: ignore[call-overload]
        row[1],  # type: ignore[arg-type]
        str(row[2]),
        tuple(str(a) for a in row[3] or ()),  # type: ignore[attr-defined]
        row[4],  # type: ignore[arg-type]
        None if row[5] is None else str(row[5]),
        None if row[6] is None else str(row[6]),
    )


def open_request() -> UpdateRequest | None:
    """Заявка, которую бот ещё не выполнил (`None` — очередь пуста)."""
    sql = (
        "select id, requested_at, requested_by, aggregators, done_at, outcome, error "
        "from agg.requests where done_at is null"
    )
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            row = conn.execute(sql).fetchone()
    except psycopg.Error as exc:
        raise _fail("Заявки на обновление агрегаторов не прочитались", exc) from exc
    return _request(row) if row else None


def request_update(aggregators: Sequence[str], *, by: str) -> tuple[UpdateRequest, bool]:
    """Поставить заявку на обновление. Пока предыдущая не выполнена, второй не
    заводится: вернётся она сама и `False`. Заявка принята — вернётся она и `True`.
    `aggregators` пусто — все, что бот собирает сам."""
    sql = (
        "insert into agg.requests (requested_by, aggregators) values (%s, %s) "
        "on conflict do nothing "
        "returning id, requested_at, requested_by, aggregators, done_at, outcome, error"
    )
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            row = conn.execute(sql, (by, list(aggregators) or None)).fetchone()
    except psycopg.Error as exc:
        raise _fail("Заявка на обновление агрегаторов не легла", exc) from exc
    if row:
        return _request(row), True
    queued = open_request()
    if queued is None:  # выполнили между вставкой и чтением — просьба ушла впустую
        raise RatingsError(
            "Заявка на обновление агрегаторов не легла: очередь сменилась, повторите"
        )
    return queued, False


def finish_request(request_id: int, *, ok: bool, error: str | None = None) -> None:
    """Закрыть заявку исходом сбора; текст ошибки обрезается, как у журнала."""
    try:
        with psycopg.connect(check_environment().dsn) as conn:
            conn.execute(
                "update agg.requests set done_at = now(), outcome = %s, error = %s "
                "where id = %s and done_at is null",
                ("ok" if ok else "failed", (error or "")[:500] or None, request_id),
            )
    except psycopg.Error as exc:
        raise _fail("Заявка на обновление агрегаторов не закрылась", exc) from exc


@dataclass(frozen=True)
class UnitRow:
    """Пиццерия из реестра. `first_seen is None` — была при первом заполнении."""

    dodo_id: str
    country: str
    name: str
    lat: float
    lng: float
    working: bool
    first_seen: date | None
    last_seen: date


_UPSERT_UNIT = """
insert into agg.units (dodo_id, country_code, name, lat, lng, working, first_seen, last_seen,
                       updated_at)
values (%s, %s, %s, %s, %s, %s, %s, %s, now())
on conflict (dodo_id) do update set
    country_code = excluded.country_code, name = excluded.name, lat = excluded.lat,
    lng = excluded.lng, working = excluded.working, last_seen = excluded.last_seen,
    updated_at = now()
"""


def save_units(units: Sequence[DodoUnit], today: date) -> int:
    """Записать реестр пиццерий; вернуть, сколько строк пришло. Новая пиццерия
    получает `first_seen = today`; известная обновляется, а `first_seen` остаётся.
    Первое заполнение (таблица была пуста) пишет `first_seen = null`: иначе
    весь список был бы «новым». Пиццерия без страны отбрасывается."""
    unique = {u.dodo_id: u for u in units if len(u.country) == 2}
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            baseline = conn.execute("select not exists (select 1 from agg.units)").fetchone()
            first = None if baseline and baseline[0] else today
            with conn.cursor() as cur:
                cur.executemany(
                    _UPSERT_UNIT,
                    [
                        (u.dodo_id, u.country, u.name, u.lat, u.lng, u.working, first, today)
                        for u in unique.values()
                    ],
                )
    except psycopg.Error as exc:
        raise _fail("Реестр пиццерий не лёг", exc) from exc
    return len(unique)


def units(countries: Sequence[str] | None = None) -> tuple[UnitRow, ...]:
    """Реестр пиццерий — все или по странам, по стране и имени."""
    sql = """
        select dodo_id, country_code, name, lat, lng, working, first_seen, last_seen
        from agg.units where (%s::text[] is null or country_code = any(%s))
        order by country_code, name, dodo_id
    """
    wanted = None if countries is None else list(countries)
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql, (wanted, wanted)).fetchall()
    except psycopg.Error as exc:
        raise _fail("Реестр пиццерий не прочитался", exc) from exc
    return tuple(
        UnitRow(str(r[0]), str(r[1]), str(r[2]), float(r[3]), float(r[4]), bool(r[5]), r[6], r[7])
        for r in rows
    )


def imf_countries() -> tuple[str, ...]:
    """Коды стран IMF из справочника рейтингов — где искать пиццерии Dodo."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select code from ratings.countries where is_imf order by code"
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("Страны IMF не прочитались", exc) from exc
    return tuple(str(r[0]) for r in rows)


def point_keys(aggregator: str) -> frozenset[str]:
    """Все ключи точек агрегатора, в том числе отмеченные «не пиццерия»."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select point_key from agg.points where aggregator = %s", (aggregator,)
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("Точки агрегатора не прочитались", exc) from exc
    return frozenset(str(r[0]) for r in rows)


@dataclass(frozen=True)
class CoverageRow:
    """Точка агрегатора, привязанная к пиццерии, и её последняя оценка (если была)."""

    aggregator: str
    dodo_id: str
    country_code: str
    score: float | None
    scale: int | None
    on_date: date | None


def coverage() -> tuple[CoverageRow, ...]:
    """Привязанные точки всех агрегаторов с последней оценкой каждой. Пиццерия,
    у которой на агрегаторе несколько точек, представлена свежайшей по дате."""
    sql = """
        select distinct on (p.aggregator, p.dodo_id)
               p.aggregator, p.dodo_id, p.country_code, r.score, r.scale, r.on_date
        from agg.points p
        left join lateral (
            select score, scale, on_date from agg.ratings
            where aggregator = p.aggregator and point_key = p.point_key
            order by on_date desc limit 1
        ) r on true
        where p.dodo_id is not null and p.excluded_reason is null
        order by p.aggregator, p.dodo_id, r.on_date desc nulls last
    """
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(sql).fetchall()
    except psycopg.Error as exc:
        raise _fail("Охват агрегаторов не прочитался", exc) from exc
    return tuple(
        CoverageRow(
            str(r[0]),
            str(r[1]),
            str(r[2]),
            None if r[3] is None else float(r[3]),
            None if r[4] is None else int(r[4]),
            r[5],
        )
        for r in rows
    )


def point_countries(aggregator: str) -> frozenset[str]:
    """Страны, где у агрегатора есть точки в справочнике."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select distinct country_code from agg.points "
                "where aggregator = %s and excluded_reason is null",
                (aggregator,),
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("Страны агрегатора не прочитались", exc) from exc
    return frozenset(str(r[0]) for r in rows)
