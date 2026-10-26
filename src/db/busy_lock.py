"""Замок «уже выполняется» между процессами (F-110): дедуп дорогих операций.

Один подбор пункта, один перевод, одна расшифровка голоса, одна сборка отчёта на чат за раз — каждый
оплачиваемый вызов модели или тяжёлая сборка. Раньше это держал набор в памяти
процесса, и второй процесс про занятость не знал. Это взаимное исключение, а не
счётчик, поэтому здесь `pg_try_advisory_lock` на ключ (пространство операции +
хеш ключа), а не строка в таблице.

Замок сессионный: держится, пока открыто соединение, поэтому на время операции
занято одно собственное соединение (не из пула: пул снимает замки на возврате).
Его можно отпустить из другого потока, чем взяли, — сборка отчёта берёт замок в
запросе, а отпускает в фоновом потоке. Умер процесс — база отпустила замок сама.

**База не отвечает — замок не мешает, а процесс остаётся под своим набором в
памяти** (`Hold.shared` — `False`): занятость внутри процесса по-прежнему держится,
между процессами временно нет. Это ослабление, а не отказ в обслуживании: сбой базы
не должен превращать «уже выполняется» в «ничего нельзя».
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import psycopg

from .config import check_environment
from .errors import DbError
from .timeouts import timed_dsn

logger = logging.getLogger(__name__)

#: Пространства замков по операциям (первая половина ключа). От номера аудита F-110,
#: чтобы владельца замка было видно в `pg_locks`; хеш ключа внутри пространства.
PROOFREAD_SUGGEST = 110_001
WALK_SUGGEST = 110_002
WALK_TRANSLATE = 110_003
WALK_REPORT = 110_004
WALK_VOICE = 110_005


@dataclass
class Hold:
    """Итог попытки занять операцию.

    `acquired` — занято нами, можно работать; `False` — идёт в другом процессе.
    `shared` — замок действительно взят в базе (`False` при недоступной базе).
    """

    acquired: bool
    shared: bool = False
    _conn: psycopg.Connection[Any] | None = None

    def release(self) -> None:
        """Отпустить замок. Безопасно звать повторно и из другого потока; не бросает."""
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.close()  # сессионный advisory-замок уходит вместе с соединением
        except psycopg.Error:
            logger.warning("Замок «уже выполняется» не закрылся чисто", exc_info=True)


def try_hold(namespace: int, key: str) -> Hold:
    """Занять операцию `key` в пространстве `namespace`. Не ждёт: занято — `acquired=False`."""
    try:
        conn = psycopg.connect(timed_dsn(check_environment().dsn), autocommit=True)
    except (psycopg.Error, DbError) as exc:
        logger.warning(
            "Замок «уже выполняется» недоступен (%s) — держим в памяти процесса", type(exc).__name__
        )
        return Hold(acquired=True)
    try:
        row = conn.execute(
            "select pg_try_advisory_lock(%s, hashtext(%s))", (namespace, key)
        ).fetchone()
    except psycopg.Error as exc:
        conn.close()
        logger.warning(
            "Замок «уже выполняется» не взялся (%s) — держим в памяти процесса", type(exc).__name__
        )
        return Hold(acquired=True)
    if row and row[0]:
        return Hold(acquired=True, shared=True, _conn=conn)
    conn.close()
    return Hold(acquired=False)
