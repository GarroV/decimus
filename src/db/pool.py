"""Общий помощник подключения к базе: пул соединений на каждый DSN.

Новое соединение стоит ~29 мс (замер на проде: 20–120), запрос на готовом —
0,13 мс. Страница админки делала 16–25 запросов к базе, каждый на своём
`psycopg.connect`, и до половины серверного времени уходило на рукопожатия.
Теперь соединение берётся из пула и возвращается в него.

Использование — вместо `with psycopg.connect(dsn) as conn:`::

    with connection(check_environment().dsn) as conn:
        ...

Семантика та же: чистый выход — `commit`, исключение — `rollback`.

Пространство обращения (`src/db/space.py`) соединение получает здесь же, на
выдаче: политики роли приложения без него не отдают ни строки (F-037).

**Что не должно утечь между пользователями.** Соединение живёт дольше запроса,
поэтому всё, что запрос оставил на сессии, увидел бы следующий — а у проекта
роли и построчные политики (миграция `0010` и др.). На возврате в пул
срабатывает `_reset`: `RESET ALL` (настройки сессии, включая `set_config(...,
false)` и `decimus.*`), `RESET ROLE` и `RESET SESSION AUTHORIZATION` (роль), снятие
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
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

from .errors import DbError
from .space import apply_space, current_space

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
    "RESET ALL; RESET ROLE; RESET SESSION AUTHORIZATION; SELECT pg_advisory_unlock_all(); "
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


@dataclass(frozen=True)
class _Config:
    max_size: int
    timeout_s: float


def _read_config() -> _Config:
    """Прочитать и проверить `DB_POOL_MAX` и `DB_POOL_TIMEOUT_S`.

    Негодное значение — одно внятное сообщение в журнал и значение по умолчанию:
    опечатка в переменной не должна ронять каждую страницу.
    """
    max_size = DEFAULT_POOL_MAX
    raw = (os.environ.get(POOL_MAX_VAR) or "").strip()
    if raw:
        if raw.isdecimal():
            max_size = int(raw)
        else:
            log.error(
                "%s=%r — нужно целое число не меньше 0; взято значение по умолчанию %s",
                POOL_MAX_VAR,
                raw,
                DEFAULT_POOL_MAX,
            )
    timeout_s = DEFAULT_POOL_TIMEOUT_S
    raw = (os.environ.get(POOL_TIMEOUT_VAR) or "").strip()
    if raw:
        try:
            timeout_s = float(raw)
            if not timeout_s > 0:
                raise ValueError(raw)
        except ValueError:
            timeout_s = DEFAULT_POOL_TIMEOUT_S
            log.error(
                "%s=%r — нужно число секунд больше 0; взято значение по умолчанию %g",
                POOL_TIMEOUT_VAR,
                raw,
                DEFAULT_POOL_TIMEOUT_S,
            )
    return _Config(max_size, timeout_s)


_config: _Config | None = None


def _settings() -> _Config:
    """Настройка читается один раз на процесс (и заново после `close_pools`)."""
    global _config
    if _config is None:
        _config = _read_config()
    return _config


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
            # Первое соединение — своё и до пула: недоступная база, неверный пароль
            # или адрес отказывают сразу и настоящей причиной, как до пула. Пул же
            # про неудачу подключения молчит и пересоединяется в фоне, а ждущий
            # увидел бы через `DB_POOL_TIMEOUT_S` лишь «нет соединения».
            psycopg.connect(dsn, connect_timeout=CONNECT_TIMEOUT_S).close()
            pool = _make_pool(dsn, max_size)
            _pools[key] = pool
    return pool


@dataclass
class _Held:
    """Соединение, взятое на весь запрос страницы (`shared_connections`)."""

    conn: psycopg.Connection[Any]
    lease: AbstractContextManager[psycopg.Connection[Any]]
    #: Пространство, переданное соединению; `None` — не передавалось.
    space: str | None = None
    busy: bool = field(default=False)


#: Соединения запроса по DSN; `None` — запрос их не делит (#732).
_SHARED: ContextVar[dict[str, _Held] | None] = ContextVar("decimus_shared_db", default=None)


@contextmanager
def shared_connections() -> Iterator[None]:
    """На время блока соединение каждого DSN берётся из пула один раз (#732).

    Страница «Обзор» делала 22 чтения, и каждое платило выдачей из пула:
    проверка соединения, передача пространства, а на возврате сброс и commit —
    около 7 мс на чтение, треть серверного времени страницы (замер 14.10.2026).
    Внутри блока чтения идут одним соединением, а в пул оно возвращается (со
    сбросом) один раз, на выходе.

    Семантика каждого `with connection()` прежняя: чистый выход — `commit`,
    исключение — `rollback`. Вложенный блок (соединение уже занято) и блок с
    ДРУГИМ пространством получают отдельное соединение, как без этого режима.
    """
    if _settings().max_size == 0 or _SHARED.get() is not None:
        yield
        return
    held: dict[str, _Held] = {}
    метка = _SHARED.set(held)
    try:
        yield
    finally:
        _SHARED.reset(метка)
        for h in held.values():
            h.lease.__exit__(None, None, None)


def _lease(dsn: str, max_size: int, timeout: float) -> _Held:
    lease = _pool_for(dsn, max_size).connection(timeout=timeout)
    try:
        conn = lease.__enter__()
    except PoolTimeout as exc:
        raise PoolBusyError(
            f"База не отдала соединение за {timeout:g} с (занята или пул мал)"
        ) from exc
    return _Held(conn=conn, lease=lease)


def _reusable(h: _Held, space: str | None) -> bool:
    """Можно ли отдать удержанное соединение этому блоку."""
    if h.busy or h.conn.closed:
        return False
    if h.conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        return False
    # Пространство только ставится, не снимается: соединение с чужим
    # пространством этому блоку не годится — он получит своё из пула.
    return h.space is None or h.space == space


@contextmanager
def _shared(held: dict[str, _Held], dsn: str, h: _Held) -> Iterator[psycopg.Connection[Any]]:
    space = current_space()
    if h.space != space and space is not None:
        apply_space(h.conn)
        h.space = space
    h.busy = True
    try:
        yield h.conn
    except BaseException as exc:
        try:
            h.conn.rollback()
        except psycopg.Error:
            # Соединение сломано: в пул — как сломанное, запросу — больше не отдавать.
            held.pop(dsn, None)
            h.lease.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        h.conn.commit()
    finally:
        h.busy = False


@contextmanager
def connection(dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """Соединение на время блока: из пула, а при `DB_POOL_MAX=0` — своё."""
    cfg = _settings()
    max_size = cfg.max_size
    if max_size == 0:
        with psycopg.connect(dsn) as conn:
            apply_space(conn)
            yield conn
        return
    timeout = cfg.timeout_s
    held = _SHARED.get()
    if held is not None:
        h = held.get(dsn)
        if h is None:
            h = held[dsn] = _lease(dsn, max_size, timeout)
        if _reusable(h, current_space()):
            with _shared(held, dsn, h) as conn:
                yield conn
            return
    try:
        with _pool_for(dsn, max_size).connection(timeout=timeout) as conn:
            apply_space(conn)
            yield conn
    except PoolTimeout as exc:
        # Тип, а не текст драйвера: в тексте бывает адрес базы.
        raise PoolBusyError(
            f"База не отдала соединение за {timeout:g} с (занята или пул мал)"
        ) from exc


def close_pools() -> None:
    """Закрыть все пулы этого процесса. Для тестов и корректного выключения."""
    global _config
    with _lock:
        pools = [p for (pid, _), p in _pools.items() if pid == os.getpid()]
        _pools.clear()
        _config = None
    for pool in pools:
        pool.close()
