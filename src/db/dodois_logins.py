"""Входы в Dodo IS по странам и ссылки-приглашения в базе (D640, миграция `0096`).

Ключи входа (доступ и продление) лежат в `vault.secrets` зашифрованными (`secret_crypto`:
AES-256-GCM, имя записи в AAD), имена — `src/domain/dodois.vault_names`. Состояние входа —
в `dodois.logins`, ссылки — в `dodois.invites` (там только хэш токена).

**Пара ключей меняется одной транзакцией.** Продление Dodo IS одноразовое: прежний ключ
продления после него мёртв, поэтому новая пара пишется вместе с отметкой продления, и либо
легло всё, либо ничего (`replace_tokens`). Упавшая запись оставляет прежнюю пару на месте.
Вход, заменённый другим за время продления, не затирается (`LoginSuperseded`).

**Чтение — ролью приложения, запись — ролью администратора истории** (как у ключей
сервисов). Значения ключей нигде не пишутся: ни в журнал процесса, ни в тексты исключений.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from src.domain.dodois import (
    CONTOURS,
    REASONS,
    STATES,
    Invite,
    Login,
    hashes_equal,
    vault_names,
)

from . import secret_crypto
from .config import check_environment
from .database_target import managing_dsn
from .errors import AccessError, DbError
from .pool import connection

logger = logging.getLogger(__name__)

PROVIDER = "dodois"
#: В `vault.secrets.last4` у ключей входа стоит заглушка: хвост настоящего ключа не хранится.
LAST4_STUB = "****"
SYSTEM_ACTOR = "system"

_LOGIN_COLUMNS = (
    "country, contour, source, issued_by, account_name, account_email, linked_at, scope, "
    "units_total, units_open, refreshed_at, access_expires_at, checked_at, state, reason"
)
_INVITE_COLUMNS = (
    "id, country, issued_by, issued_at, expires_at, used_at, revoked_at, token_hash, "
    "issued_by_id::text, issued_by_role, issued_by_tenant"
)

_VAULT_UPSERT = """
insert into vault.secrets (name, provider, ciphertext, last4, set_by, set_at)
values (%s, %s, %s, %s, %s, now())
on conflict (name) do update
set provider = excluded.provider, ciphertext = excluded.ciphertext, last4 = excluded.last4,
    set_by = excluded.set_by, set_at = excluded.set_at
"""


class LoginSuperseded(DbError):
    """Вход страны заменён другим, пока шло продление: старая пара больше не нужна."""


class InviteUnusable(DbError):
    """Ссылка погашена, отозвана или её уже нет: вход по ней не записывается."""


@dataclass(frozen=True)
class Tokens:
    """Ключи входа страны. Ни в журнал, ни в текст исключения не попадают."""

    access: str
    refresh: str

    def __repr__(self) -> str:  # значения не светятся даже в отладочном выводе
        return "Tokens(<скрыто>)"


def _login(row: Any) -> Login:
    return Login(*row)


def _invite(row: Any) -> Invite:
    return Invite(*row)


def _fail(what: str, exc: psycopg.Error) -> DbError:
    return AccessError(f"{what}: база отказала ({exc.__class__.__name__})")


def _managing() -> Any:
    _, dsn = managing_dsn("поменять вход Dodo IS")
    return psycopg.connect(dsn)


def _read(sql: str, params: tuple[Any, ...], what: str) -> list[Any]:
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())
    except psycopg.Error as exc:
        raise _fail(what, exc) from exc


# --- входы ----------------------------------------------------------------------------


def list_logins() -> tuple[Login, ...]:
    rows = _read(
        f"select {_LOGIN_COLUMNS} from dodois.logins order by country",  # noqa: S608
        (),
        "Входы Dodo IS не прочитались",
    )
    return tuple(_login(r) for r in rows)


def get_login(country: str) -> Login | None:
    vault_names(country)
    rows = _read(
        f"select {_LOGIN_COLUMNS} from dodois.logins where country = %s",  # noqa: S608
        (country,),
        "Вход Dodo IS не прочитался",
    )
    return _login(rows[0]) if rows else None


def read_tokens(country: str) -> Tokens | None:
    """Ключи входа страны, расшифрованные; `None` — их в базе нет. Нет `SECRETS_KEY` — отказ."""
    access_name, refresh_name = vault_names(country)
    rows = _read(
        "select name, ciphertext from vault.secrets where name in (%s, %s)",
        (access_name, refresh_name),
        "Ключи входа Dodo IS не прочитались",
    )
    found = {str(r[0]): bytes(r[1]) for r in rows}
    if access_name not in found or refresh_name not in found:
        return None
    return Tokens(
        access=secret_crypto.decrypt(access_name, found[access_name]),
        refresh=secret_crypto.decrypt(refresh_name, found[refresh_name]),
    )


def _put_tokens(cur: Any, country: str, tokens: Tokens, by: str) -> None:
    access_name, refresh_name = vault_names(country)
    for name, value in ((access_name, tokens.access), (refresh_name, tokens.refresh)):
        cur.execute(
            _VAULT_UPSERT,
            (name, PROVIDER, secret_crypto.encrypt(name, value), LAST4_STUB, by),
        )


def save_login(
    *,
    country: str,
    contour: str,
    source: str,
    issued_by: str,
    account_name: str | None,
    account_email: str | None,
    scope: str,
    tokens: Tokens,
    access_expires_at: datetime,
    now: datetime,
    invite_id: int | None = None,
) -> Login:
    """Записать вход страны (заменяет прежний) вместе с ключами и погашением ссылки.

    Одна транзакция: ссылка погашается, только если она ещё жива; иначе `InviteUnusable` и
    не записано ничего.
    """
    # Шифруем до соединения: нет `SECRETS_KEY` — отказ до любой записи.
    vault_names(country)
    if contour not in CONTOURS:
        raise ValueError("Контур не из списка")
    try:
        with _managing() as conn, conn.cursor() as cur:
            if invite_id is not None:
                cur.execute(
                    "update dodois.invites set used_at = %s where id = %s and country = %s "
                    "and used_at is null and revoked_at is null",
                    (now, invite_id, country),
                )
                if cur.rowcount != 1:
                    raise InviteUnusable("Ссылка уже использована или отозвана")
            _put_tokens(cur, country, tokens, issued_by)
            cur.execute(
                """
                insert into dodois.logins (country, contour, source, issued_by, account_name,
                    account_email, linked_at, scope, refreshed_at, access_expires_at, state)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ok')
                on conflict (country) do update set contour = excluded.contour,
                    source = excluded.source, issued_by = excluded.issued_by,
                    account_name = excluded.account_name, account_email = excluded.account_email,
                    linked_at = excluded.linked_at, scope = excluded.scope,
                    units_total = null, units_open = null, checked_at = null,
                    refreshed_at = excluded.refreshed_at,
                    access_expires_at = excluded.access_expires_at,
                    state = 'ok', reason = null
                """,
                (
                    country,
                    contour,
                    source,
                    issued_by,
                    account_name,
                    account_email,
                    now,
                    scope,
                    now,
                    access_expires_at,
                ),
            )
    except psycopg.Error as exc:
        raise _fail("Вход Dodo IS не записался", exc) from exc
    login = get_login(country)
    if login is None:  # записали и не видим: разные базы у ролей
        raise AccessError("Вход Dodo IS записан, но не читается")
    return login


def replace_tokens(
    *,
    country: str,
    tokens: Tokens,
    access_expires_at: datetime,
    scope: str | None,
    now: datetime,
    expect_linked_at: datetime,
) -> None:
    """Новая пара ключей после продления — одной транзакцией с отметкой продления.

    Любой сбой откатывает всё: прежняя пара остаётся. Вход заменён другим (`linked_at`
    не тот) — `LoginSuperseded`, ничего не записано.
    """
    vault_names(country)
    try:
        with _managing() as conn, conn.cursor() as cur:
            cur.execute(
                "update dodois.logins set refreshed_at = %s, access_expires_at = %s, "
                "scope = coalesce(%s, scope) where country = %s and linked_at = %s",
                (now, access_expires_at, scope, country, expect_linked_at),
            )
            if cur.rowcount != 1:
                raise LoginSuperseded("Вход страны заменён, пока шло продление")
            _put_tokens(cur, country, tokens, SYSTEM_ACTOR)
    except psycopg.Error as exc:
        raise _fail("Новая пара ключей Dodo IS не записалась", exc) from exc


def record_state(
    country: str,
    state: str,
    reason: str | None,
    *,
    now: datetime,
    units_total: int | None = None,
    units_open: int | None = None,
) -> None:
    """Состояние входа после проверки или отказа; счёт пиццерий не затирается, если не передан."""
    vault_names(country)
    if state not in STATES or (reason is not None and reason not in REASONS):
        raise ValueError("Состояние или причина входа не из списка")
    try:
        with _managing() as conn, conn.cursor() as cur:
            cur.execute(
                "update dodois.logins set state = %s, reason = %s, checked_at = %s, "
                "units_total = coalesce(%s, units_total), units_open = coalesce(%s, units_open) "
                "where country = %s",
                (state, reason, now, units_total, units_open, country),
            )
    except psycopg.Error as exc:
        raise _fail("Состояние входа Dodo IS не записалось", exc) from exc


# --- приглашения ----------------------------------------------------------------------


def create_invite(
    *,
    country: str,
    token_hash: str,
    issued_by: str,
    issued_by_id: str,
    issued_by_role: str,
    issued_by_tenant: str,
    now: datetime,
    expires_at: datetime,
) -> int:
    """Записать ссылку (хэш токена); номер приглашения."""
    vault_names(country)
    try:
        with _managing() as conn, conn.cursor() as cur:
            cur.execute(
                "insert into dodois.invites (country, token_hash, issued_by, issued_by_id, "
                "issued_by_role, issued_by_tenant, issued_at, expires_at) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
                (
                    country,
                    token_hash,
                    issued_by,
                    issued_by_id,
                    issued_by_role,
                    issued_by_tenant,
                    now,
                    expires_at,
                ),
            )
            row = cur.fetchone()
    except psycopg.Error as exc:
        raise _fail("Ссылка не записалась", exc) from exc
    return int(row[0])


def find_invite(token_hash: str) -> Invite | None:
    """Приглашение по хэшу токена; сверка хэшей — за постоянное время."""
    rows = _read(
        f"select {_INVITE_COLUMNS} from dodois.invites where token_hash = %s",  # noqa: S608
        (token_hash,),
        "Ссылка не прочиталась",
    )
    for row in rows:
        invite = _invite(row)
        if hashes_equal(invite.token_hash, token_hash):
            return invite
    return None


def get_invite(invite_id: int) -> Invite | None:
    rows = _read(
        f"select {_INVITE_COLUMNS} from dodois.invites where id = %s",  # noqa: S608
        (invite_id,),
        "Ссылка не прочиталась",
    )
    return _invite(rows[0]) if rows else None


def list_invites(limit: int = 30) -> tuple[Invite, ...]:
    """Последние приглашения, свежие первыми, — для статуса в админке (без токенов)."""
    rows = _read(
        f"select {_INVITE_COLUMNS} from dodois.invites "  # noqa: S608
        "order by issued_at desc, id desc limit %s",
        (limit,),
        "Ссылки не прочитались",
    )
    return tuple(_invite(r) for r in rows)


def revoke_invite(invite_id: int, now: datetime) -> bool:
    """Отозвать живую ссылку; `False` — отзывать было нечего (погашена, отозвана)."""
    try:
        with _managing() as conn, conn.cursor() as cur:
            cur.execute(
                "update dodois.invites set revoked_at = %s where id = %s "
                "and used_at is null and revoked_at is null",
                (now, invite_id),
            )
            return bool(cur.rowcount == 1)
    except psycopg.Error as exc:
        raise _fail("Ссылка не отозвалась", exc) from exc
