"""Общее скользящее окно частоты запросов (F-110, миграция `0082`).

Предел частоты MCP и мини-аппа обхода считался в памяти процесса: второй
контейнер или перекрытие при выкатке видели каждый свою половину запросов, и
предел удваивался. Здесь окно общее — в таблице `rate_windows`, тем же приёмом,
что счётчик входов (`web_throttle`): чтение-правка-запись идёт под
рекомендательным замком на ключ, иначе параллельные процессы читали бы одно
число и пропускали запрос оба.

**Семантика окна прежняя.** Окно скользящее: запрос учитывается, пока с него не
прошло `window`; предел выбран — отказ, и отказанный запрос НЕ учитывается.
Меняется только место хранения и часы: время берёт база (`clock_timestamp()`),
а не монотонные часы процесса, которые у разных процессов несравнимы.

**База не отвечает — `None`, а не отказ и не пропуск вслепую** (`try_allow`):
вызывающий считает по окну своего процесса, как раньше. Предел при этом
ослабевает до одного процесса, но не пропадает и не роняет запрос; сбой идёт в
журнал не чаще раза в минуту.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from .config import check_environment
from .errors import DbError, RateWindowError
from .pool import connection

logger = logging.getLogger(__name__)

#: Пространство рекомендательных замков окна: номер аудита, чтобы владельца замка
#: было видно в `pg_locks` (так же, как `325` у счётчика входов).
ADVISORY_NAMESPACE = 110

#: Замок на ключ, а не на строку: первой записи по ключу ещё нет, и
#: `select ... for update` не запер бы ничего.
_ADVISORY_LOCK_SQL = "select pg_advisory_xact_lock(%s, hashtext(%s))"

_LOAD_SQL = """
    select clock_timestamp(),
           (select stamps from rate_windows where scope = %s and key_fingerprint = %s)
"""

_SAVE_SQL = """
    insert into rate_windows (scope, key_fingerprint, stamps, updated_at)
    values (%s, %s, %s, %s)
    on conflict (scope, key_fingerprint) do update
       set stamps = excluded.stamps, updated_at = excluded.updated_at
"""

#: Попутная чистка: строки, у которых всё окно давно позади. `skip locked` — чужую
#: занятую строку пропускаем, а не ждём (иначе две попытки запирали бы друг друга,
#: как в T331); потолок на одно обращение — хвост рассасывается за несколько.
_DROP_STALE_SQL = """
    delete from rate_windows
     where ctid in (
         select ctid from rate_windows
          where scope = %s and updated_at < %s
          limit %s
            for update skip locked
     )
"""

#: Сколько просроченных строк убирает одно обращение.
DROP_STALE_BATCH = 100

#: Как часто сбой общего окна попадает в журнал, секунд.
_LOG_EVERY_SEC = 60.0
_log_state = {"last": float("-inf")}
_log_lock = threading.Lock()


def key_fingerprint(value: str) -> str:
    """Ключ предела → отпечаток, который единственный попадает в базу (SHA-256, 64 знака)."""
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()


def admit(
    stamps: Sequence[datetime], *, now: datetime, window: timedelta, limit: int
) -> tuple[tuple[datetime, ...], bool]:
    """Решение окна по отметкам. Чистая функция: в базу не ходит.

    Возвращает отметки ПОСЛЕ решения и пропущен ли запрос. Просроченные
    (`now - отметка >= window`) отсекаются; выбран предел — отметки возвращаются
    без новой, запрос не учтён.
    """
    live = tuple(s for s in stamps if now - s < window)
    if len(live) >= limit:
        return live, False
    return (*live, now), True


@contextmanager
def _connected() -> Iterator[psycopg.Connection[Any]]:
    """Подключение роли приложения. Отказ базы — `RateWindowError`, а не голый драйвер."""
    try:
        with connection(check_environment().dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise RateWindowError(f"Общее окно частоты недоступно ({type(exc).__name__})") from exc


def allow(
    *, scope: str, key: str, limit: int, window_sec: float, now: datetime | None = None
) -> bool:
    """Учесть запрос в общем окне; `False` — предел за окно выбран, запрос не учтён.

    `now` — только для проверок: в продукте время берёт база. Не отвечает база —
    `RateWindowError` (а при незаданной `DATABASE_URL` — `ConfigError`); решение
    «что тогда» принимает вызывающий (`try_allow`).
    """
    fingerprint = key_fingerprint(key)
    window = timedelta(seconds=window_sec)
    with _connected() as conn, conn.cursor() as cur:
        cur.execute(_ADVISORY_LOCK_SQL, (ADVISORY_NAMESPACE, f"{scope}\x1f{fingerprint}"))
        cur.execute(_LOAD_SQL, (scope, fingerprint))
        row = cur.fetchone()
        assert row is not None  # noqa: S101 — select без from строку отдаёт всегда
        at = (now or row[0]).astimezone(UTC)
        stamps, admitted = admit(row[1] or (), now=at, window=window, limit=limit)
        if admitted:
            cur.execute(_SAVE_SQL, (scope, fingerprint, list(stamps), at))
        cur.execute(_DROP_STALE_SQL, (scope, at - window, DROP_STALE_BATCH))
    return admitted


def _note_unavailable(exc: DbError) -> None:
    """Сбой общего окна — в журнал, но не чаще раза в минуту: предел стоит на горячем пути."""
    with _log_lock:
        now = time.monotonic()
        if now - _log_state["last"] < _LOG_EVERY_SEC:
            return
        _log_state["last"] = now
    logger.warning("Общее окно частоты недоступно — считаем в окне процесса: %s", exc)


def try_allow(*, scope: str, key: str, limit: int, window_sec: float) -> bool | None:
    """`allow`, но без исключений: `None` — общее окно недоступно, считать в памяти процесса."""
    try:
        return allow(scope=scope, key=key, limit=limit, window_sec=window_sec)
    except DbError as exc:
        _note_unavailable(exc)
        return None
