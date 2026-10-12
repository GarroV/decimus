"""Общий помощник подключения к базе: пул соединений на каждый DSN.

Новое соединение стоит ~29 мс (замер на проде: 20–120), запрос на готовом —
0,13 мс. Страница админки делала 16–25 запросов к базе, каждый на своём
`psycopg.connect`, и до половины серверного времени уходило на рукопожатия.
Теперь соединение берётся из пула и возвращается в него.

Использование — вместо `with psycopg.connect(dsn) as conn:`::

    with connection(check_environment().dsn) as conn:
        ...

Семантика та же: чистый выход — `commit`, исключение — `rollback`.

**Что не должно утечь между пользователями.** Соединение живёт дольше запроса,
поэтому всё, что запрос оставил на сессии, увидел бы следующий — а у проекта
роли и построчные политики (миграция `0010` и др.). На возврате в пул
срабатывает `_reset`: `RESET ALL` (настройки сессии, включая `set_config(...,
false)` и `decimus.*`), `RESET SESSION AUTHORIZATION` (роль), снятие
advisory-замков, `UNLISTEN *`, `CLOSE ALL`, `DISCARD TEMP`. Соединение в незавершённой или
упавшей транзакции пул откатывает сам до `_reset`; если после сброса оно не
чистое — выбрасывает. Все `set_config` и `SET` в коде и так транзакционно
локальны (`set_config(..., true)`, `set local`), сброс — страховка от
следующего, кто напишет иначе. Тест: `tests/test_db_pool.py`.

Не `DISCARD ALL`: он сбрасывает подготовленные выражения на сервере, а кеш
драйвера об этом не знает — следующий запрос упал бы «prepared statement does
not exist».

Пул на каждый DSN отдельно (обычная роль и администратор истории — разные
строки), создаётся лениво, в процессе-владельце: после `fork` потомок заводит
свои пулы заново. Отказ дождаться соединения — `PoolBusyError`: и `DbError`,
и `psycopg.Error`, поэтому существующие `except psycopg.Error` в дверях
переводят его в свои ошибки, а текст без адреса базы.

Настройка (необязательная): `DB_POOL_MAX` — потолок соединений на DSN (по
умолчанию 8; `0` — пул выключен, каждое обращение открывает своё, как до
пула), `DB_POOL_TIMEOUT_S` — сколько ждать свободное соединение (по умолчанию
10 с).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from .errors import DbError

log = logging.getLogger(__name__)

POOL_MAX_VAR = "DB_POOL_MAX"
POOL_TIMEOUT_VAR = "DB_POOL_TIMEOUT_S"

DEFAULT_POOL_MAX = 8
DEFAULT_POOL_TIMEOUT_S = 10.0
#: Держим наготове одно соединение: первый запрос после тишины не платит рукопожатием.
POOL_MIN_SIZE = 1
#: Срок на установку НОВОГО соединения (не на ожидание свободного из пула).
CONNECT_TIMEOUT_S = 10

#: Что вернуть соединению перед следующим пользователем: настройки, роль,
#: advisory-замки, подписки, курсоры, временные таблицы.
RESET_SQL = (
    "RESET ALL; RESET SESSION AUTHORIZATION; SELECT pg_advisory_unlock_all(); "
    "UNLISTEN *; CLOSE ALL; DISCARD TEMP"
)


class PoolBusyError(DbError, psycopg.OperationalError):
    """Свободного соединения не нашлось за отведённый срок: база занята или пул мал."""


def _reset(conn: psycopg.Connection[Any]) -> None:
    """Вернуть соединение в чистое состояние перед выдачей следующему.

    Пул вызывает это после отката и ждёт на выходе соединение вне транзакции.
    `RESET ALL` и остальное не требуют блока транзакции, но драйвер открыл бы
    его неявно — поэтому на время сброса включаем автокоммит.
    """
    conn.set_autocommit(True)
    try:
        conn.execute(RESET_SQL)
    finally:
        conn.set_autocommit(False)


def _env_number(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        log.error("%s=%r не число, берём %s", name, raw, default)
        return default
    return value if value >= 0 else default


_pools: dict[tuple[int, str], ConnectionPool[Any]] = {}
_lock = threading.Lock()


def _make_pool(dsn: str, max_size: int) -> ConnectionPool[Any]:
    pool: ConnectionPool[Any] = ConnectionPool(
        dsn,
        min_size=min(POOL_MIN_SIZE, max_size),
        max_size=max_size,
        kwargs={"connect_timeout": CONNECT_TIMEOUT_S},
        # Проверка на выдаче: соединение, которое база или сеть уже закрыли
        # за время простоя, не доходит до запроса и не рушит страницу.
        check=ConnectionPool.check_connection,
        reset=_reset,
        open=False,
        name="decimus-db",
    )
    pool.open()
    return pool


def _pool_for(dsn: str, max_size: int) -> ConnectionPool[Any]:
    key = (os.getpid(), dsn)
    pool = _pools.get(key)
    if pool is not None:
        return pool
    with _lock:
        pool = _pools.get(key)
        if pool is None:
            pool = _make_pool(dsn, max_size)
            _pools[key] = pool
    return pool


@contextmanager
def connection(dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """Соединение на время блока: из пула, а при `DB_POOL_MAX=0` — своё."""
    max_size = int(_env_number(POOL_MAX_VAR, DEFAULT_POOL_MAX))
    if max_size == 0:
        with psycopg.connect(dsn) as conn:
            yield conn
        return
    timeout = _env_number(POOL_TIMEOUT_VAR, DEFAULT_POOL_TIMEOUT_S)
    try:
        with _pool_for(dsn, max_size).connection(timeout=timeout) as conn:
            yield conn
    except PoolTimeout as exc:
        # Тип, а не текст драйвера: в тексте бывает адрес базы.
        raise PoolBusyError(
            f"База не отдала соединение за {timeout:g} с (занята или пул мал)"
        ) from exc


def close_pools() -> None:
    """Закрыть все пулы этого процесса. Для тестов и корректного выключения."""
    with _lock:
        pools = [p for (pid, _), p in _pools.items() if pid == os.getpid()]
        _pools.clear()
    for pool in pools:
        pool.close()
