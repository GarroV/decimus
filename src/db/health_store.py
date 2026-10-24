"""Двери базы для вкладки «Подключения» (D638): исходы проб и последние заходы сборов.

Пробы пишет фоновая задача бота (`src/bot/health_loader.py`) в `health.checks`, по
строке на подключение. Сборы читаются из их собственных журналов загрузок — отдельной
проверки у них нет: журнал и есть факт того, что загрузчик ходит и чем это кончилось.
Таблица контроля читается своей дверью (`ratings_sync.states`), там есть охват.
"""

from __future__ import annotations

from datetime import datetime

import psycopg

from src.domain.health import LoadFacts, ProbeRow

from . import ratings_sync
from .config import check_environment
from .errors import DbError
from .pool import connection

#: Журналы загрузок сборов с одной строкой на заход: код сбора → таблица.
_LOAD_TABLES = {
    "maps": "maps.loads",
    "learning": "learning.loads",
}


def _fail(what: str, exc: psycopg.Error) -> DbError:
    return DbError(f"{what}: база отказала ({exc.__class__.__name__})")


def record(code: str, light: str, reason: str, checked_at: datetime) -> None:
    """Записать исход пробы; прежний исход того же подключения заменяется."""
    try:
        with connection(check_environment().dsn) as conn:
            conn.execute(
                "insert into health.checks (code, light, reason, checked_at) "
                "values (%s, %s, %s, %s) on conflict (code) do update set "
                "light = excluded.light, reason = excluded.reason, "
                "checked_at = excluded.checked_at",
                (code, light, reason, checked_at),
            )
    except psycopg.Error as exc:
        raise _fail("Исход проверки подключения не записался", exc) from exc


def probes() -> dict[str, ProbeRow]:
    """Последние исходы проб по коду подключения."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                "select code, light, reason, checked_at from health.checks"
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("Исходы проверок подключений не прочитались", exc) from exc
    return {r[0]: ProbeRow(light=r[1], reason=r[2], checked_at=r[3]) for r in rows}


def _single(table: str) -> LoadFacts | None:
    # Имя таблицы — только из `_LOAD_TABLES`, не из запроса.
    sql = f"select at, outcome, error from {table} order by at desc limit 1"  # noqa: S608
    with connection(check_environment().dsn) as conn:
        row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return LoadFacts(at=row[0], ok=row[1] == "ok", error=row[2])


def _aggregators() -> LoadFacts | None:
    """Сводный заход агрегаторов: последний по каждому, упавшие — в ошибке поимённо."""
    with connection(check_environment().dsn) as conn:
        rows = conn.execute(
            "select distinct on (aggregator) aggregator, at, outcome, error "
            "from agg.loads order by aggregator, at desc"
        ).fetchall()
    if not rows:
        return None
    failed = [f"{r[0]}: {r[3] or '—'}" for r in rows if r[2] != "ok"]
    return LoadFacts(
        at=max(r[1] for r in rows),
        ok=not failed,
        error="; ".join(failed)[:500] or None,
    )


def _sheet() -> LoadFacts | None:
    """Таблица контроля: последний заход по всем листам; упавший лист — сбой."""
    states = ratings_sync.states()
    if not states:
        return None
    failed = [s for s in states if s.outcome == "failed"]
    return LoadFacts(
        at=max(s.checked_at for s in states),
        ok=not failed,
        error="; ".join(f"{s.tab}: {s.note or '—'}" for s in failed)[:500] or None,
    )


def loads() -> dict[str, LoadFacts | None]:
    """Последний заход каждого сбора по его журналу; `None` — ещё не ходил."""
    try:
        found: dict[str, LoadFacts | None] = {
            code: _single(table) for code, table in _LOAD_TABLES.items()
        }
        found["aggregators"] = _aggregators()
    except psycopg.Error as exc:
        raise _fail("Журналы сборов не прочитались", exc) from exc
    found["sheet"] = _sheet()
    return found
