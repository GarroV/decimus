"""Ключи внешних сервисов из базы (D576, обобщение ключа модели D491).

Записи лежат в `vault.secrets` зашифрованными (`secret_crypto`: AES-256-GCM, имя записи
в AAD, ключ шифрования `SECRETS_KEY` — только в окружении сервера). Ставит их главный
админ на экране «Подключения»; процессы читают ролью приложения и расшифровывают у себя.

**Порядок чтения — `resolve`:** база, затем переменная окружения из реестра. Нет записи —
работает прежний `.env`, поэтому площадка не ломается до первой вставки.

**Имя — только из реестра** (`src/domain/service_keys.VAULT_NAMES`): любое другое отклоняется
до обращения к базе, а `check` таблицы (`0084`) не примет его и там.

**Кэш в процессе — `CACHE_SECONDS`**, на каждое имя свой. Смена значения применяется во
всех процессах в течение минуты; в процессе, где значение меняли, кэш сбрасывается сразу.

**Сбой чтения не роняет работу.** База недоступна или шифртекст не открылся — в журнал
процесса идёт строка с ТИПОМ сбоя (не со значением), берётся окружение.

**Значение нигде не пишется:** ни в журнал, ни в тексты исключений. Наружу из записи уходят
сервис, последние четыре знака, кто и когда поставил.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any

import psycopg

from src.domain.service_keys import LAST_CHARS, SERVICES, VAULT_NAMES, field_of, service

from . import secret_crypto
from .config import check_environment
from .database_target import managing_dsn
from .errors import AccessError, DbError
from .pool import connection

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0
#: Сбой чтения запоминается ненадолго: упавшая база не должна получать соединение на каждый вызов.
FAILURE_CACHE_SECONDS = 15.0

_READ_SQL = "select ciphertext from vault.secrets where name = %s"
_STATUS_SQL = "select provider, last4, set_by, set_at from vault.secrets where name = %s"
_ALL_STATUS_SQL = "select name, provider, last4, set_by, set_at from vault.secrets"
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
    """Что видно о записи на экране: никогда не само значение."""

    provider: str
    last4: str
    set_by: str
    set_at: datetime

    @property
    def masked(self) -> str:
        return "••••" + self.last4


@dataclass(frozen=True)
class ProbeSnapshot:
    """Internal-only effective credentials and version. Never serialize or log these fields."""

    values: dict[str, str] = field(repr=False)
    fingerprint: bytes = field(repr=False)
    _statuses: dict[str, KeyStatus] | None = field(default=None, repr=False)


def _service_lock(conn: Any, code: str) -> None:
    # PostgreSQL hash + fixed namespace: stable across processes and connections.
    conn.execute(
        "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
        ("decimus:service-key-health:" + code,),
    )


def _named_locks(conn: Any, names: Any) -> tuple[str, ...]:
    codes = tuple(sorted(s.code for s in SERVICES if any(f.vault_name in names for f in s.fields)))
    for code in codes:
        _service_lock(conn, code)
    return codes


def _invalidate_health(conn: Any, codes: tuple[str, ...]) -> None:
    for code in codes:
        conn.execute(
            "update health.checks set light = 'grey', "
            "reason = 'health.reason.credentials_recheck' where code = %s",
            (code,),
        )


def probe_snapshot(code: str, *, conn: Any = None) -> ProbeSnapshot:
    """Fresh DB→ENV snapshot under a short per-service lock, without resolver cache.

    With an existing connection the caller retains that transaction and lock. HTTP
    must happen only after the standalone snapshot transaction has closed.
    """
    found = service(code)
    if found is None:
        raise AccessError("Сервис не из реестра")
    try:
        if conn is None:
            with connection(check_environment().dsn) as opened:
                return probe_snapshot(code, conn=opened)
        _service_lock(conn, code)
        names = [f.vault_name for f in found.fields]
        rows = conn.execute(
            "select name, ciphertext, set_at, provider, last4, set_by from vault.secrets "
            "where name = any(%s)",
            (names,),
        ).fetchall()
        stored_rows = {row[0]: (bytes(row[1]), row[2]) for row in rows}
        values: dict[str, str] = {}
        versions = []
        for key_field in found.fields:
            item = stored_rows.get(key_field.vault_name)
            value = None
            if item is not None:
                try:
                    value = secret_crypto.decrypt(key_field.vault_name, item[0]).strip() or None
                except DbError as exc:
                    logger.warning("Версия ключа: расшифровка недоступна (%s)", type(exc).__name__)
            source = "db" if value else "env"
            if not value:
                value = (os.environ.get(key_field.env_var) or "").strip()
            values[key_field.code] = value
            versions.append(
                (
                    key_field.vault_name,
                    source,
                    value,
                    (item[0].hex(), item[1].isoformat()) if item else None,
                )
            )
        fingerprint = hashlib.sha256(json.dumps(versions, ensure_ascii=True).encode()).digest()
        statuses = {
            str(row[0]): KeyStatus(str(row[3]), str(row[4]), str(row[5]), row[2]) for row in rows
        }
        return ProbeSnapshot(values, fingerprint, statuses)
    except psycopg.Error as exc:
        raise AccessError(
            "Не удалось прочитать версию ключей (" + type(exc).__name__ + ")"
        ) from exc


_lock = Lock()
#: имя → (когда прочитано, сколько жить, значение).
_cache: dict[str, tuple[float, float, str | None]] = {}


def _forget(name: str | None = None) -> None:
    with _lock:
        if name is None:
            _cache.clear()
        else:
            _cache.pop(name, None)


def _known(name: str) -> str:
    if name not in VAULT_NAMES:
        # Имя приходит из реестра; сюда попасть чужому имени нечем — но отказ дешевле догадки.
        raise AccessError("Имя секрета не из реестра")
    return name


def _read_decrypted(name: str) -> str | None:
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_READ_SQL, (name,))
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось прочитать ключ сервиса ({type(exc).__name__})") from exc
    if row is None:
        return None
    return secret_crypto.decrypt(name, bytes(row[0]))


def stored(name: str) -> str | None:
    """Значение из базы (расшифрованное) или `None`; не дольше `CACHE_SECONDS` назад.

    Любой сбой — `None` и строка в журнал процесса с типом сбоя: вызывающий берёт окружение.
    """
    _known(name)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(name)
        if hit is not None and now - hit[0] < hit[1]:
            return hit[2]
    try:
        value = _read_decrypted(name)
    except DbError as exc:
        logger.warning(
            "ключ сервиса из базы не прочитан (%s), берётся окружение", type(exc).__name__
        )
        with _lock:
            _cache[name] = (now, FAILURE_CACHE_SECONDS, None)
        return None
    with _lock:
        _cache[name] = (now, CACHE_SECONDS, value)
    return value


def resolve(service_code: str, field_code: str, env: Mapping[str, str] | None = None) -> str | None:
    """Значение поля сервиса: база, затем окружение; нигде нет — `None`."""
    field = field_of(service_code, field_code)
    if field is None:
        raise AccessError("Поле не из реестра сервисов")
    value = stored(field.vault_name)
    if value:
        return value.strip() or None
    raw = (os.environ if env is None else env).get(field.env_var) or ""
    return raw.strip() or None


def _row(row: Any) -> KeyStatus:
    return KeyStatus(provider=str(row[0]), last4=str(row[1]), set_by=str(row[2]), set_at=row[3])


def status(name: str) -> KeyStatus | None:
    """Запись без значения; `None` — в базе её нет."""
    _known(name)
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_STATUS_SQL, (name,))
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось прочитать ключ сервиса ({type(exc).__name__})") from exc
    return None if row is None else _row(row)


def statuses() -> dict[str, KeyStatus]:
    """Все записи одним чтением: имя → запись без значения."""
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            cur.execute(_ALL_STATUS_SQL)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось прочитать ключи сервисов ({type(exc).__name__})") from exc
    return {str(r[0]): _row(r[1:]) for r in rows}


def _managing() -> Any:
    _, dsn = managing_dsn("поменять ключ сервиса")
    return psycopg.connect(dsn)


def save_many(values: Mapping[str, str], *, provider: str, by: str) -> dict[str, KeyStatus]:
    """Положить значения (имя → значение) одной транзакцией; ничего не записано при сбое.

    Нет `SECRETS_KEY` — отказ до записи. Возвращает записи без значений.
    """
    blobs = {}
    for name, raw in values.items():
        value = raw.strip()
        blobs[_known(name)] = (secret_crypto.encrypt(name, value), value[-LAST_CHARS:])
    try:
        with _managing() as conn, conn.cursor() as cur:
            codes = _named_locks(conn, blobs)
            for name, (blob, last4) in blobs.items():
                cur.execute(_UPSERT_SQL, (name, provider, blob, last4, by))
            _invalidate_health(conn, codes)
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось поменять ключ сервиса ({type(exc).__name__})") from exc
    for name in blobs:
        _forget(name)
    return {name: found for name in blobs if (found := status(name)) is not None}


def clear_many(names: tuple[str, ...]) -> bool:
    """Убрать записи из базы — дальше работает окружение. `False` — убирать было нечего."""
    for name in names:
        _known(name)
    try:
        with _managing() as conn, conn.cursor() as cur:
            codes = _named_locks(conn, names)
            removed = 0
            for name in names:
                cur.execute(_DELETE_SQL, (name,))
                removed += cur.rowcount
            if removed:
                _invalidate_health(conn, codes)
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось убрать ключ сервиса ({type(exc).__name__})") from exc
    for name in names:
        _forget(name)
    return removed > 0
