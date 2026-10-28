"""Запись данных Dodo IS для «Качества» (D671, миграция `0105`): замена месяца и журнал загрузки.

Месяц заменяется целиком для пиццерий, ответивших в этот заход: их строки месяца удаляются
и вставляются заново одной транзакцией, так что упавший заход оставляет прежний месяц. Строк
заказов и данных клиентов здесь нет — только агрегаты «пиццерия × месяц». Читает эти таблицы
`src/db/dodois_metrics.py`.

Бот пишет ролью приложения от имени служебного пространства (F-037).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from src.domain.dodois_metrics import (
    AggregatorMonth,
    CheckupPeriod,
    KrRow,
    RatingPeriod,
    SalesRow,
)

from .config import check_environment
from .errors import RatingsError
from .pool import connection

_ERROR_LIMIT = 500

_DEL_SALES = "delete from dodois.unit_sales_month where month = %s and dodo_id = any(%s)"
_DEL_AGG = "delete from dodois.unit_aggregator_month where month = %s and dodo_id = any(%s)"
_DEL_KR = "delete from dodois.unit_kr_month where month = %s and dodo_id = any(%s)"

_INS_SALES = (
    "insert into dodois.unit_sales_month "
    "(dodo_id, month, order_source, sales_channel, orders, revenue, currency) "
    "values (%s, %s, %s, %s, %s, %s, %s)"
)
_INS_AGG = (
    "insert into dodois.unit_aggregator_month (dodo_id, month, aggregator, orders, revenue) "
    "values (%s, %s, %s, %s, %s)"
)
_INS_KR = (
    "insert into dodois.unit_kr_month "
    "(dodo_id, month, dine_in_avg, dine_in_count, delivery_avg, delivery_count) "
    "values (%s, %s, %s, %s, %s, %s)"
)


def _failed(what: str, exc: psycopg.Error) -> RatingsError:
    return RatingsError(f"{what}: база отказала ({exc.__class__.__name__})")


def _replace(
    delete: str, insert: str, month: date, units: Sequence[str], rows: list[tuple[Any, ...]]
) -> int:
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            conn.execute(delete, (month, list(units)))
            with conn.cursor() as cur:
                cur.executemany(insert, rows)
    except psycopg.Error as exc:
        raise _failed("Данные Dodo IS не легли", exc) from exc
    return len(rows)


def replace_sales(month: date, units: Sequence[str], rows: Sequence[SalesRow]) -> int:
    """Заменить продажи месяца у `units`; вернуть, сколько строк легло."""
    data = [
        (r.dodo_id, month, r.order_source, r.sales_channel, r.orders, r.revenue, r.currency)
        for r in rows
    ]
    return _replace(_DEL_SALES, _INS_SALES, month, units, data)


def replace_aggregators(month: date, units: Sequence[str], rows: Sequence[AggregatorMonth]) -> int:
    """Заменить заказы агрегаторов месяца у `units`."""
    data = [(r.dodo_id, month, r.aggregator, r.orders, r.revenue) for r in rows]
    return _replace(_DEL_AGG, _INS_AGG, month, units, data)


def replace_kr(month: date, units: Sequence[str], rows: Sequence[KrRow]) -> int:
    """Заменить оценки клиентов месяца у `units`; пиццерия без единой оценки строки не получает."""
    data = [
        (r.dodo_id, month, r.dine_in_avg, r.dine_in_count, r.delivery_avg, r.delivery_count)
        for r in rows
        if r.dine_in_count or r.delivery_count
    ]
    return _replace(_DEL_KR, _INS_KR, month, units, data)


_DEL_RATING = (
    "delete from dodois.unit_rating_period "
    "where period_from between %s and %s and dodo_id = any(%s)"
)
_DEL_CHECKUP = (
    "delete from dodois.unit_checkup_period "
    "where period_from between %s and %s and dodo_id = any(%s)"
)
_INS_RATING = (
    "insert into dodois.unit_rating_period "
    "(dodo_id, kind, period_from, period_to, rate, publish_status) values (%s, %s, %s, %s, %s, %s)"
)
_INS_CHECKUP = (
    "insert into dodois.unit_checkup_period "
    "(dodo_id, kind, period_from, period_to, checkups, by_status) values (%s, %s, %s, %s, %s, %s)"
)


def _replace_range(
    delete: str,
    insert: str,
    start: date,
    stop: date,
    units: Sequence[str],
    rows: list[tuple[Any, ...]],
) -> int:
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            conn.execute(delete, (start, stop, list(units)))
            with conn.cursor() as cur:
                cur.executemany(insert, rows)
    except psycopg.Error as exc:
        raise _failed("Данные Dodo IS не легли", exc) from exc
    return len(rows)


def replace_rating_periods(
    start: date, stop: date, units: Sequence[str], rows: Sequence[RatingPeriod]
) -> int:
    """Заменить оценки РКО и РС у `units` за периоды, начавшиеся между `start` и `stop`."""
    data = [(r.dodo_id, r.kind, r.period_from, r.period_to, r.rate, r.publish_status) for r in rows]
    return _replace_range(_DEL_RATING, _INS_RATING, start, stop, units, data)


def replace_checkup_periods(
    start: date, stop: date, units: Sequence[str], rows: Sequence[CheckupPeriod]
) -> int:
    """Заменить счёт проверок у `units` за периоды, начавшиеся между `start` и `stop`."""
    data = [
        (r.dodo_id, r.kind, r.period_from, r.period_to, r.checkups, Jsonb(r.by_status))
        for r in rows
    ]
    return _replace_range(_DEL_CHECKUP, _INS_CHECKUP, start, stop, units, data)


def start_load(country: str, kind: str) -> int | None:
    """Открыть строку журнала; вернуть её номер. Отказ журнала — `None`, загрузку не отменяет."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute(
                "insert into dodois.metric_loads (country, kind) values (%s, %s) returning id",
                (country, kind),
            ).fetchone()
    except psycopg.Error:
        return None
    return int(row[0]) if row else None


def finish_load(load_id: int | None, *, ok: bool, rows: int = 0, error: str | None = None) -> None:
    """Закрыть строку журнала исходом. Сам отказ журнала — `RatingsError`: тихо терять нельзя."""
    if load_id is None:
        return
    try:
        with connection(check_environment().dsn) as conn:
            conn.execute(
                "update dodois.metric_loads set finished_at = now(), ok = %s, rows = %s, "
                "error = %s where id = %s",
                (ok, rows, (error or "")[:_ERROR_LIMIT] or None, load_id),
            )
    except psycopg.Error as exc:
        raise _failed("Журнал сбора Dodo IS не записался", exc) from exc


def has_ok_load(country: str, kind: str) -> bool:
    """Была ли у страны хоть одна удачная загрузка этого вида (нет — пора заполнять историю)."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute(
                "select exists (select 1 from dodois.metric_loads "
                "where country = %s and kind = %s and ok)",
                (country, kind),
            ).fetchone()
    except psycopg.Error as exc:
        raise _failed("Журнал сбора Dodo IS не прочитался", exc) from exc
    return bool(row and row[0])


def last_ok_at(country: str, kind: str) -> datetime | None:
    """Когда последний раз удалась загрузка этого вида (`None` — ни разу)."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute(
                "select max(finished_at) from dodois.metric_loads "
                "where country = %s and kind = %s and ok",
                (country, kind),
            ).fetchone()
    except psycopg.Error as exc:
        raise _failed("Журнал сбора Dodo IS не прочитался", exc) from exc
    return row[0] if row else None


def country_units(country: str) -> list[str]:
    """Коды пиццерий страны из рейтингов (`ratings.units`)."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select dodo_id from ratings.units where country_code = %s order by dodo_id",
                (country,),
            ).fetchall()
    except psycopg.Error as exc:
        raise _failed("Пиццерии страны не прочитались", exc) from exc
    return [str(r[0]) for r in rows]
