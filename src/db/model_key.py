"""Ключ модели из базы (D491): запись, чтение, кэш на минуту.

Ключ провайдера вставляет главный админ на экране «Подключения»; здесь он лежит
зашифрованным (`secret_crypto`, `vault.secrets`), а процессы — бот, веб, обход —
читают его ролью приложения и расшифровывают у себя. Нет записи в базе — работает
прежний `OPENAI_API_KEY` из окружения, поэтому площадка не ломается до первой вставки.

**Кэш в процессе — `CACHE_SECONDS`.** Смена ключа применяется во всех процессах в течение
минуты без перезапуска; в процессе, где ключ меняли, кэш сбрасывается сразу.

**Сбой чтения не роняет разбор.** База недоступна или шифртекст не открылся — в журнал
процесса идёт строка с ТИПОМ сбоя (не со значением), ключ берётся из окружения.

**Ключ нигде не пишется:** ни в журнал, ни в тексты исключений. Наружу из записи уходят
провайдер, последние четыре знака, кто и когда поставил.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

import psycopg

from . import secret_crypto
from .config import check_environment
from .database_target import managing_dsn
from .errors import AccessError, DbError
from .pool import connection

logger = logging.getLogger(__name__)

NAME = "model_key"
PROVIDER_OPENAI = "openai"
CACHE_SECONDS = 60.0
#: Сбой чтения запоминается ненадолго: упавшая база не должна получать соединение на каждый вызов.
FAILURE_CACHE_SECONDS = 15.0
LAST_CHARS = 4

_READ_SQL = "select ciphertext from vault.secrets where name = %s"
_STATUS_SQL = "select provider, last4, set_by, set_at from vault.secrets where name = %s"
_UPSERT_SQL = """
insert into vault.secrets (name, provider, ciphertext, last4, set_by, set_at)
values (%s, %s, %s, %s, %s, now())
on conflict (name) do update
set provider = excluded.provider, ciphertext = excluded.ciphertext, last4 = excluded.last4,
    set_by = excluded.set_by, set_at = excluded.set_at
"""
_DELETE_SQL = "delete from vault.secrets where name = %s"


@dataclass(frozen=True)
class KeyStatus:
    """Что видно о ключе на экране: никогда не сам ключ."""

    provider: str
    last4: str
    set_by: str
    set_at: datetime

    @property
    def masked(self) -> str:
        return "••••" + self.last4


_lock = Lock()
#: (когда прочитано, сколько жить, значение).
_cache: tuple[float, float, str | None] | None = None


def _forget() -> None:
    global _cache
    with _lock:
        _cache = None


def _read_decrypted() -> str | None:
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_READ_SQL, (NAME,))
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось прочитать ключ модели ({type(exc).__name__})") from exc
    if row is None:
        return None
    return secret_crypto.decrypt(NAME, bytes(row[0]))


def stored_key() -> str | None:
    """Ключ модели из базы (расшифрованный) или `None`; не дольше `CACHE_SECONDS` назад.

    Любой сбой — `None` и строка в журнал процесса с типом сбоя: вызывающий берёт окружение.
    """
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cache[0] < _cache[1]:
            return _cache[2]
    try:
        value = _read_decrypted()
    except DbError as exc:
        logger.warning(
            "ключ модели из базы не прочитан (%s), берётся окружение", type(exc).__name__
        )
        with _lock:
            _cache = (now, FAILURE_CACHE_SECONDS, None)
        return None
    with _lock:
        _cache = (now, CACHE_SECONDS, value)
    return value


def status() -> KeyStatus | None:
    """Запись о ключе без самого ключа; `None` — в базе ключа нет."""
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_STATUS_SQL, (NAME,))
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось прочитать ключ модели ({type(exc).__name__})") from exc
    if row is None:
        return None
    return KeyStatus(provider=str(row[0]), last4=str(row[1]), set_by=str(row[2]), set_at=row[3])


def _managing() -> Any:
    _, dsn = managing_dsn("поменять ключ модели")
    return psycopg.connect(dsn)


def save(value: str, *, by: str, provider: str = PROVIDER_OPENAI) -> KeyStatus:
    """Положить ключ (заменить прежний). Нет `SECRETS_KEY` — отказ, ничего не записано."""
    value = value.strip()
    blob = secret_crypto.encrypt(NAME, value)
    try:
        with _managing() as conn, conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, (NAME, provider, blob, value[-LAST_CHARS:], by))
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось поменять ключ модели ({type(exc).__name__})") from exc
    _forget()
    found = status()
    if found is None:
        raise AccessError("Ключ модели не найден после записи")
    return found


def clear() -> bool:
    """Убрать ключ из базы — дальше работает окружение. `False` — убирать было нечего."""
    try:
        with _managing() as conn, conn.cursor() as cur:
            cur.execute(_DELETE_SQL, (NAME,))
            removed: bool = cur.rowcount > 0
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось убрать ключ модели ({type(exc).__name__})") from exc
    _forget()
    return removed
