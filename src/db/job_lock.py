"""Замки плановых загрузчиков бота (F-125): один процесс на загрузку.

Загрузчики карт и таблицы контроля решают «пора ли» по отметке последней удачной
загрузки в базе и затем грузят. Между проверкой и загрузкой другой процесс
(перекрывшийся контейнер при выкатке, второй экземпляр) видит ту же отметку, и оба
тянут из внешнего источника и пишут: двойная нагрузка на квоту и задвоенные строки.
Замок делает «один» правилом базы — тем же приёмом, что у сборщика агрегаторов
(`agg_store.collector_lock`, #788): `pg_try_advisory_lock` на соединении, которое
держится на время загрузки.

Замок рекомендательный, сессионный: отпускается базой, даже если процесс умер
посреди загрузки. Не взялся — `False`: загрузку уже ведёт другой процесс, этот тик
молча пропускается, это не ошибка.

Ключи замков — одним списком здесь, чтобы два загрузчика не взяли один номер.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from .config import check_environment
from .errors import RatingsError
from .timeouts import timed_dsn

#: Замок сборщика агрегаторов (#788) живёт в `agg_store.COLLECTOR_LOCK_KEY` = 788_0001.
#: Новые номера берутся от номера аудита (F-125), чтобы владельца замка было видно в `pg_locks`.
MAPS_LOADER_LOCK_KEY = 125_0001
SHEET_LOADER_LOCK_KEY = 125_0002


@contextmanager
def job_lock(key: int, *, what: str) -> Iterator[bool]:
    """Замок загрузчика на время его захода: `True` — взят, `False` — уже идёт в другом процессе.

    `what` — как загрузка названа в тексте отказа базы. Отказ базы — `RatingsError`,
    как у соседних дверей загрузчиков.
    """
    try:
        conn = psycopg.connect(timed_dsn(check_environment().dsn, batch=True), autocommit=True)
    except psycopg.Error as exc:
        raise RatingsError(
            f"Замок загрузки «{what}» не взят: база отказала ({exc.__class__.__name__})"
        ) from exc
    with conn:
        row = conn.execute("select pg_try_advisory_lock(%s)", (key,)).fetchone()
        got = bool(row and row[0])
        try:
            yield got
        finally:
            if got:
                conn.execute("select pg_advisory_unlock(%s)", (key,))
