"""Пределы ожидания базы по умолчанию для обычных соединений (F-119).

До этого предел ставило одно место (предписания УК); остальные соединения
ждали запрос и замок без срока, и один зависший запрос или чужая транзакция
держали бы работника, пул и страницу до рестарта.

`timed_dsn(dsn)` возвращает ту же строку подключения с добавленными
`statement_timeout`, `lock_timeout` (стартовые параметры сервера, `options`) и
`connect_timeout`. Уже заданное в самой строке не перекрывается; `SET` на
сессии (предписания УК, `set local` в коде) сильнее стартового значения, а
`RESET ALL` пула возвращает именно к нему.

Не касается: наката миграций (`migrate.py`), подключений владельца схемы и
администратора истории, одноразовых инструментов `tools/` — им срок задаёт
своё место или не нужен вовсе.

Настройка (необязательная): `DB_STATEMENT_TIMEOUT_S` (по умолчанию 30),
`DB_LOCK_TIMEOUT_S` (по умолчанию 10), `DB_BATCH_STATEMENT_TIMEOUT_S` (пакетные
загрузки рейтингов, по умолчанию 300); `0` — не ставить. Выключатель нужен для
пулера, не принимающего стартовый параметр `options` (при переезде на
Supabase), и для долгой разовой выгрузки.
"""

from __future__ import annotations

import logging
import os

from psycopg.conninfo import conninfo_to_dict, make_conninfo

log = logging.getLogger(__name__)

STATEMENT_TIMEOUT_VAR = "DB_STATEMENT_TIMEOUT_S"
LOCK_TIMEOUT_VAR = "DB_LOCK_TIMEOUT_S"
BATCH_STATEMENT_TIMEOUT_VAR = "DB_BATCH_STATEMENT_TIMEOUT_S"

DEFAULT_STATEMENT_TIMEOUT_S = 30
DEFAULT_LOCK_TIMEOUT_S = 10
#: Пакетные загрузки рейтингов (сборщик агрегаторов, синхронизация, импорт
#: выгрузки) вправе идти дольше интерактивного запроса: длинная загрузка — не
#: вектор отказа, а обрыв её на 30-й секунде — регресс.
DEFAULT_BATCH_STATEMENT_TIMEOUT_S = 300
#: Срок на установку нового соединения.
CONNECT_TIMEOUT_S = 10


def _seconds(var: str, default: int) -> int:
    raw = (os.environ.get(var) or "").strip()
    if not raw:
        return default
    if raw.isdecimal():
        return int(raw)
    log.error("%s=%r — нужно целое число секунд не меньше 0; взято %s", var, raw, default)
    return default


def timed_dsn(dsn: str, *, batch: bool = False) -> str:
    """Строка подключения со сроками по умолчанию; заданное в ней не трогается.

    `batch=True` — пакетные загрузки рейтингов: срок запроса из
    `DB_BATCH_STATEMENT_TIMEOUT_S` (300 с), остальные сроки те же.
    """
    given = conninfo_to_dict(dsn)
    extra: dict[str, str] = {}
    if "connect_timeout" not in given:
        extra["connect_timeout"] = str(CONNECT_TIMEOUT_S)
    if "options" not in given:
        flags = []
        for name, var, default in (
            (
                "statement_timeout",
                BATCH_STATEMENT_TIMEOUT_VAR if batch else STATEMENT_TIMEOUT_VAR,
                DEFAULT_BATCH_STATEMENT_TIMEOUT_S if batch else DEFAULT_STATEMENT_TIMEOUT_S,
            ),
            ("lock_timeout", LOCK_TIMEOUT_VAR, DEFAULT_LOCK_TIMEOUT_S),
        ):
            seconds = _seconds(var, default)
            if seconds:
                flags.append(f"-c {name}={seconds * 1000}")
        if flags:
            extra["options"] = " ".join(flags)
    return make_conninfo(dsn, **extra) if extra else dsn
