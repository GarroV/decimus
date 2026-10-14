"""Вторая ступень входа (D463, `0068`): хранение и одноразовые переходы.

Правила — в `src/domain/second_factor.py`, проверка ключей доступа — в
`src/web/webauthn_rp.py`; здесь только база. Всё, что обязано случиться ровно один
раз, случается ОДНИМ запросом с условием, а не «прочитал — решил — записал»:

* полупройденный вход гасится `update … where consumed_at is null … returning`;
* резервный код — так же (`used_at is null`);
* принятый шаг TOTP — `update … where last_step is null or last_step < новый`;
* счётчик ключа доступа — `update … where sign_count = прежний`;
* вызов ключа — `delete … returning`.

Проигравший гонку получает пустой ответ и отказ. Последний способ входа админа не снять:
проверка и удаление идут под одним рекомендательным замком учётки.

Отказ базы — `AccessError` (`web_access._connected`), а не «такого нет».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.domain.second_factor import (
    CHALLENGE_TTL,
    MAX_PENDING_FAILURES,
    PENDING_TTL,
    removal_leaves_required_factor,
)

from .web_access import _connected, _managing, new_session_token, session_fingerprint

#: Пространство рекомендательных замков второй ступени (рядом: 325 — счётчик попыток).
ADVISORY_NAMESPACE = 463

_LOCK_SQL = "select pg_advisory_xact_lock(%s, hashtext(%s))"

#: Что вернул способ удаления.
REMOVED = "removed"
MISSING = "missing"
LAST_FACTOR = "last-factor"

PURPOSE_REGISTER = "register"
PURPOSE_AUTHENTICATE = "authenticate"
#: Вход ключом с формы входа (D485): вызов выдан без учётки, привязка — кука браузера.
PURPOSE_LOGIN = "login"


@dataclass(frozen=True)
class Passkey:
    """Ключ доступа человека."""

    id: str
    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: tuple[str, ...]
    name: str
    created_at: datetime
    last_used_at: datetime | None


@dataclass(frozen=True)
class TotpRow:
    """Приложение-аутентификатор: секрет, подтверждено ли и последний принятый шаг."""

    secret: str
    confirmed: bool
    last_step: int | None


@dataclass(frozen=True)
class Status:
    """Какие способы входа у человека подключены."""

    passkeys: tuple[Passkey, ...]
    totp_confirmed: bool
    totp_pending: bool
    backup_left: int

    @property
    def has_factor(self) -> bool:
        """Есть ли способ входа (резервные коды способом не считаются)."""
        return bool(self.passkeys) or self.totp_confirmed

    @property
    def factor_count(self) -> int:
        return len(self.passkeys) + (1 if self.totp_confirmed else 0)


@dataclass(frozen=True)
class Pending:
    """Полупройденный вход: первая ступень пройдена, вторая нет."""

    id: str
    user_id: str
    method: str
    next_path: str | None
    expires_at: datetime
    failures: int


def _passkey(row: Any) -> Passkey:
    return Passkey(
        id=str(row[0]),
        credential_id=bytes(row[1]),
        public_key=bytes(row[2]),
        sign_count=int(row[3]),
        transports=tuple(row[4] or ()),
        name=str(row[5]),
        created_at=row[6],
        last_used_at=row[7],
    )


# --- состояние -------------------------------------------------------------------


def status_of(user_id: str) -> Status:
    """Способы входа человека и сколько резервных кодов не погашено."""
    with _connected("прочитать способы входа") as conn, conn.cursor() as cur:
        cur.execute(
            "select id, credential_id, public_key, sign_count, transports, name,"
            " created_at, last_used_at from web_passkeys where user_id = %s order by created_at",
            (user_id,),
        )
        ключи = tuple(_passkey(r) for r in cur.fetchall())
        cur.execute("select confirmed_at is not null from web_totp where user_id = %s", (user_id,))
        строка = cur.fetchone()
        cur.execute(
            "select count(*) from web_backup_codes where user_id = %s and used_at is null",
            (user_id,),
        )
        осталось = cur.fetchone()
    return Status(
        passkeys=ключи,
        totp_confirmed=bool(строка and строка[0]),
        totp_pending=строка is not None and not строка[0],
        backup_left=int(осталось[0]) if осталось else 0,
    )


def has_any(user_id: str) -> bool:
    """Подключён ли хоть один способ входа (ключ доступа или подтверждённое приложение)."""
    with _connected("узнать, есть ли вторая ступень") as conn, conn.cursor() as cur:
        cur.execute(
            "select exists (select 1 from web_passkeys where user_id = %(u)s)"
            " or exists (select 1 from web_totp"
            " where user_id = %(u)s and confirmed_at is not null)",
            {"u": user_id},
        )
        строка = cur.fetchone()
    return bool(строка and строка[0])


# --- полупройденный вход ---------------------------------------------------------


def open_pending(user_id: str, *, method: str, next_path: str | None) -> str:
    """Начать полупройденный вход. Токен уезжает в куку браузера, в базе — отпечаток."""
    токен = new_session_token()
    with _connected("начать вторую ступень входа") as conn, conn.cursor() as cur:
        # Попутная чистка: отжившее (срок вышел больше суток назад) не копится.
        cur.execute("delete from web_second_steps where expires_at < now() - interval '1 day'")
        cur.execute(
            "insert into web_second_steps (user_id, fingerprint, method, next_path, expires_at)"
            " values (%s, %s, %s, %s, now() + %s)",
            (user_id, session_fingerprint(токен), method, next_path, PENDING_TTL),
        )
    return токен


def _pending(row: Any) -> Pending:
    return Pending(
        id=str(row[0]),
        user_id=str(row[1]),
        method=str(row[2]),
        next_path=row[3],
        expires_at=row[4],
        failures=int(row[5]),
    )


def find_pending(token: str) -> Pending | None:
    """Живой полупройденный вход по токену из куки; погашенный, просроченный, мёртвый — `None`."""
    with _connected("найти вторую ступень входа") as conn, conn.cursor() as cur:
        cur.execute(
            "select id, user_id, method, next_path, expires_at, failures from web_second_steps"
            " where fingerprint = %s and consumed_at is null and expires_at > now()"
            " and failures < %s",
            (session_fingerprint(token), MAX_PENDING_FAILURES),
        )
        строка = cur.fetchone()
    return None if строка is None else _pending(строка)


def note_pending_failure(token: str) -> int:
    """Записать неверный ответ; вернуть, сколько их уже. Пять — вход мёртв."""
    with _connected("записать неверный ответ второй ступени") as conn, conn.cursor() as cur:
        cur.execute(
            "update web_second_steps set failures = failures + 1"
            " where fingerprint = %s and consumed_at is null returning failures",
            (session_fingerprint(token),),
        )
        строка = cur.fetchone()
    return int(строка[0]) if строка else MAX_PENDING_FAILURES


def consume_pending(token: str) -> Pending | None:
    """Погасить полупройденный вход — одним движением. Только первый вызов вернёт строку.

    Живой, не погашенный, не просроченный, не мёртвый от неудач: иначе `None`.
    """
    with _connected("погасить вторую ступень входа") as conn, conn.cursor() as cur:
        cur.execute(
            "update web_second_steps set consumed_at = now()"
            " where fingerprint = %s and consumed_at is null and expires_at > now()"
            " and failures < %s returning id, user_id, method, next_path, expires_at, failures",
            (session_fingerprint(token), MAX_PENDING_FAILURES),
        )
        строка = cur.fetchone()
    return None if строка is None else _pending(строка)


# --- вызовы ключей доступа -------------------------------------------------------


def store_challenge(bound_token: str, *, purpose: str, user_id: str, challenge: bytes) -> None:
    """Запомнить вызов за привязкой (полупройденный вход или сессия). Прежний вытесняется."""
    отпечаток = session_fingerprint(bound_token)
    with _connected("запомнить вызов ключа доступа") as conn, conn.cursor() as cur:
        cur.execute("delete from web_webauthn_challenges where expires_at < now()")
        cur.execute(
            "delete from web_webauthn_challenges where bound_fp = %s and purpose = %s",
            (отпечаток, purpose),
        )
        cur.execute(
            "insert into web_webauthn_challenges"
            " (bound_fp, purpose, user_id, challenge, expires_at)"
            " values (%s, %s, %s, %s, now() + %s)",
            (отпечаток, purpose, user_id, challenge, CHALLENGE_TTL),
        )


def take_challenge(bound_token: str, *, purpose: str, user_id: str) -> bytes | None:
    """Снять вызов — ОДИН раз. Нет, чужой, просроченный — `None`; снятый не вернётся."""
    with _connected("снять вызов ключа доступа") as conn, conn.cursor() as cur:
        cur.execute(
            "delete from web_webauthn_challenges where bound_fp = %s and purpose = %s"
            " returning challenge, user_id, expires_at > now()",
            (session_fingerprint(bound_token), purpose),
        )
        строка = cur.fetchone()
    if строка is None or str(строка[1]) != str(user_id) or not строка[2]:
        return None
    return bytes(строка[0])


def store_login_challenge(bound_token: str, *, challenge: bytes) -> None:
    """Запомнить вызов входа ключом за кукой браузера, без учётки. Прежний вытесняется."""
    отпечаток = session_fingerprint(bound_token)
    with _connected("запомнить вызов входа ключом") as conn, conn.cursor() as cur:
        cur.execute("delete from web_webauthn_challenges where expires_at < now()")
        cur.execute(
            "delete from web_webauthn_challenges where bound_fp = %s and purpose = %s",
            (отпечаток, PURPOSE_LOGIN),
        )
        cur.execute(
            "insert into web_webauthn_challenges"
            " (bound_fp, purpose, user_id, challenge, expires_at)"
            " values (%s, %s, null, %s, now() + %s)",
            (отпечаток, PURPOSE_LOGIN, challenge, CHALLENGE_TTL),
        )


def take_login_challenge(bound_token: str) -> bytes | None:
    """Снять вызов входа ключом — ОДИН раз. Нет или просрочен — `None`; снятый не вернётся."""
    with _connected("снять вызов входа ключом") as conn, conn.cursor() as cur:
        cur.execute(
            "delete from web_webauthn_challenges where bound_fp = %s and purpose = %s"
            " returning challenge, expires_at > now()",
            (session_fingerprint(bound_token), PURPOSE_LOGIN),
        )
        строка = cur.fetchone()
    if строка is None or not строка[1]:
        return None
    return bytes(строка[0])


# --- ключи доступа ---------------------------------------------------------------


def _close_others_if_first(cur: Any, user_id: str, keep_session_id: str | None) -> None:
    """Если способов входа ещё нет — закрыть прочие сессии человека (D463).

    Сессия, открытая одной первой ступенью до подключения способа, иначе пережила бы его:
    украденный пароль, которым зашли раньше хозяина, остался бы действующим входом.
    """
    cur.execute(
        "select (select count(*) from web_passkeys where user_id = %(u)s)"
        " + (select count(*) from web_totp where user_id = %(u)s and confirmed_at is not null)",
        {"u": user_id},
    )
    строка = cur.fetchone()
    if строка is None or int(строка[0]) > 0:
        return
    cur.execute(
        "update web_sessions set closed_at = now()"
        " where user_id = %s and closed_at is null and id is distinct from %s",
        (user_id, keep_session_id),
    )


def add_passkey(
    user_id: str,
    *,
    credential_id: bytes,
    public_key: bytes,
    sign_count: int,
    transports: tuple[str, ...],
    name: str,
    keep_session_id: str | None = None,
) -> Passkey:
    """Записать новый ключ доступа. Первый способ человека закрывает его ДРУГИЕ сессии."""
    with _connected("записать ключ доступа") as conn, conn.cursor() as cur:
        _close_others_if_first(cur, user_id, keep_session_id)
        cur.execute(
            "insert into web_passkeys (user_id, credential_id, public_key, sign_count,"
            " transports, name) values (%s, %s, %s, %s, %s, %s)"
            " returning id, credential_id, public_key, sign_count, transports, name,"
            " created_at, last_used_at",
            (user_id, credential_id, public_key, sign_count, list(transports), name),
        )
        строка = cur.fetchone()
    assert строка is not None  # noqa: S101 — insert … returning без строки не бывает
    return _passkey(строка)


def factors_all_newer_than(user_id: str, since: datetime) -> bool:
    """Все способы входа человека созданы не раньше `since` (или их нет): до этой сессии их не было.

    Так узнаётся сессия, которой человек подключил ПЕРВЫЙ способ: ей можно продолжить настройку
    (резервные коды) без доказательства ступени. Сессия при уже имевшемся способе — нельзя.
    """
    with _connected("сверить давность способов входа") as conn, conn.cursor() as cur:
        cur.execute(
            "select not exists (select 1 from web_passkeys where user_id = %(u)s"
            "                    and created_at < %(s)s)"
            "   and not exists (select 1 from web_totp where user_id = %(u)s"
            "                    and confirmed_at is not null and confirmed_at < %(s)s)",
            {"u": user_id, "s": since},
        )
        строка = cur.fetchone()
    return bool(строка and строка[0])


def purge_idle_passkeys(
    idle: timedelta,
) -> tuple[tuple[str, str, str, int], ...]:
    """Снять ключи, которыми не входили `idle` (`last_used_at`, у неиспользованных `created_at`).

    Вернуть по человеку: (номер учётки, роль, пространство, сколько ключей снято).
    """
    with _connected("снять ключи доступа, которыми не входили") as conn, conn.cursor() as cur:
        cur.execute(
            "with gone as ("
            " delete from web_passkeys"
            "  where coalesce(last_used_at, created_at) < now() - %s returning user_id)"
            " select g.user_id, u.role, u.tenant_code, count(*)"
            "   from gone g join web_users u on u.id = g.user_id"
            "  group by g.user_id, u.role, u.tenant_code",
            (idle,),
        )
        return tuple((str(r[0]), str(r[1]), str(r[2]), int(r[3])) for r in cur.fetchall())


def passkey_by_credential(credential_id: bytes) -> tuple[Passkey, str] | None:
    """Ключ доступа по номеру и номер учётки-владельца; нет такого — `None`."""
    with _connected("найти ключ доступа") as conn, conn.cursor() as cur:
        cur.execute(
            "select id, credential_id, public_key, sign_count, transports, name,"
            " created_at, last_used_at, user_id from web_passkeys where credential_id = %s",
            (credential_id,),
        )
        строка = cur.fetchone()
    return None if строка is None else (_passkey(строка), str(строка[8]))


def touch_passkey(passkey_id: str, *, old_count: int, new_count: int) -> bool:
    """Принять новый счётчик ключа — только если в базе всё ещё прежний (гонка проигрывает)."""
    with _connected("обновить счётчик ключа доступа") as conn, conn.cursor() as cur:
        cur.execute(
            "update web_passkeys set sign_count = %s, last_used_at = now()"
            " where id = %s and sign_count = %s",
            (new_count, passkey_id, old_count),
        )
        return cur.rowcount > 0


def _removal(user_id: str, delete_sql: str, params: tuple[Any, ...], *, minus_passkey: bool) -> str:
    """Удалить способ входа, если админу после этого остаётся другой. Под замком учётки."""
    with _connected("убрать способ входа") as conn, conn.cursor() as cur:
        cur.execute(_LOCK_SQL, (ADVISORY_NAMESPACE, str(user_id)))
        cur.execute("select role from web_users where id = %s", (user_id,))
        роль = cur.fetchone()
        if роль is None:
            return MISSING
        cur.execute(
            "select (select count(*) from web_passkeys where user_id = %(u)s),"
            " exists (select 1 from web_totp where user_id = %(u)s and confirmed_at is not null)",
            {"u": user_id},
        )
        счёт = cur.fetchone()
        assert счёт is not None  # noqa: S101 — агрегат без FROM строку отдаёт всегда
        ключей, есть_приложение = int(счёт[0]), bool(счёт[1])
        # Способ, который уходит, в остаток не входит; резервные коды способом не считаются.
        останется = (ключей - 1) + int(есть_приложение) if minus_passkey else ключей
        if not removal_leaves_required_factor(role=str(роль[0]), remaining_factors=останется):
            return LAST_FACTOR
        cur.execute(delete_sql, params)
        return REMOVED if cur.rowcount > 0 else MISSING


def remove_passkey(user_id: str, passkey_id: str) -> str:
    """Убрать СВОЙ ключ доступа. `REMOVED` / `MISSING` / `LAST_FACTOR` (админу последний нельзя)."""
    return _removal(
        user_id,
        "delete from web_passkeys where id = %s and user_id = %s",
        (passkey_id, user_id),
        minus_passkey=True,
    )


def remove_totp(user_id: str) -> str:
    """Убрать приложение-аутентификатор. Админу, если это последний способ, нельзя."""
    return _removal(
        user_id,
        "delete from web_totp where user_id = %s and confirmed_at is not null",
        (user_id,),
        minus_passkey=False,
    )


# --- приложение-аутентификатор ---------------------------------------------------


def begin_totp(user_id: str, secret: str) -> bool:
    """Завести неподтверждённое приложение. `False` — подтверждённое уже есть."""
    with _connected("начать подключение приложения") as conn, conn.cursor() as cur:
        cur.execute(_LOCK_SQL, (ADVISORY_NAMESPACE, str(user_id)))
        cur.execute("select confirmed_at is not null from web_totp where user_id = %s", (user_id,))
        строка = cur.fetchone()
        if строка is not None and строка[0]:
            return False
        cur.execute("delete from web_totp where user_id = %s", (user_id,))
        cur.execute("insert into web_totp (user_id, secret) values (%s, %s)", (user_id, secret))
    return True


def totp_of(user_id: str) -> TotpRow | None:
    """Приложение человека (подтверждённое или нет); нет — `None`."""
    with _connected("прочитать приложение-аутентификатор") as conn, conn.cursor() as cur:
        cur.execute(
            "select secret, confirmed_at is not null, last_step from web_totp where user_id = %s",
            (user_id,),
        )
        строка = cur.fetchone()
    if строка is None:
        return None
    return TotpRow(
        secret=str(строка[0]),
        confirmed=bool(строка[1]),
        last_step=None if строка[2] is None else int(строка[2]),
    )


def confirm_totp(user_id: str, *, step: int, keep_session_id: str | None = None) -> bool:
    """Подтвердить приложение первым верным кодом; его шаг запоминается (повтор не пройдёт).

    Первый способ человека закрывает его ДРУГИЕ сессии (кроме `keep_session_id`).
    """
    with _connected("подтвердить приложение") as conn, conn.cursor() as cur:
        _close_others_if_first(cur, user_id, keep_session_id)
        cur.execute(
            "update web_totp set confirmed_at = now(), last_step = %s"
            " where user_id = %s and confirmed_at is null",
            (step, user_id),
        )
        return cur.rowcount > 0


def accept_totp_step(user_id: str, *, step: int) -> bool:
    """Принять шаг кода — только новее последнего принятого. `False` — повтор или гонка."""
    with _connected("принять код приложения") as conn, conn.cursor() as cur:
        cur.execute(
            "update web_totp set last_step = %s where user_id = %s and confirmed_at is not null"
            " and (last_step is null or last_step < %s)",
            (step, user_id, step),
        )
        return cur.rowcount > 0


# --- резервные коды --------------------------------------------------------------


def replace_backup_codes(user_id: str, hashes: tuple[str, ...]) -> None:
    """Заменить набор резервных кодов: прежние (и погашенные) перестают действовать."""
    with _connected("выпустить резервные коды") as conn, conn.cursor() as cur:
        cur.execute(_LOCK_SQL, (ADVISORY_NAMESPACE, str(user_id)))
        cur.execute("delete from web_backup_codes where user_id = %s", (user_id,))
        cur.executemany(
            "insert into web_backup_codes (user_id, code_hash) values (%s, %s)",
            [(user_id, h) for h in hashes],
        )


def use_backup_code(user_id: str, code_hash: str) -> bool:
    """Погасить резервный код. Только первый вызов вернёт `True`: код одноразовый."""
    with _connected("погасить резервный код") as conn, conn.cursor() as cur:
        cur.execute(
            "update web_backup_codes set used_at = now()"
            " where user_id = %s and code_hash = %s and used_at is null",
            (user_id, code_hash),
        )
        return cur.rowcount > 0


# --- сброс -----------------------------------------------------------------------


def _reset(cur: Any, user_id: str) -> int:
    cur.execute(
        "update web_sessions set closed_at = now() where user_id = %s and closed_at is null",
        (user_id,),
    )
    cur.execute("delete from web_webauthn_challenges where user_id = %s", (user_id,))
    cur.execute("delete from web_second_steps where user_id = %s", (user_id,))
    cur.execute("delete from web_backup_codes where user_id = %s", (user_id,))
    cur.execute("delete from web_passkeys where user_id = %s", (user_id,))
    ключей = int(cur.rowcount)
    cur.execute("delete from web_totp where user_id = %s", (user_id,))
    return ключей + int(cur.rowcount)


def reset_all(user_id: str) -> int:
    """Сбросить вторую ступень человека целиком: ключи, приложение, резервные коды, начатые входы.

    Рука администратора истории (`0068`), а не роли приложения. Открытые сессии человека
    закрываются: сброс делают, когда ключ или телефон потеряны или украдены, и вошедший
    ими остаться не должен. Вернуть: сколько способов входа (ключей и приложение) снято.
    """
    with _managing("сбросить вторую ступень входа") as conn, conn.cursor() as cur:
        return _reset(cur, user_id)


@dataclass(frozen=True)
class ResetOutcome:
    """Кому сбросили вторую ступень командой с сервера."""

    user_id: str
    role: str
    tenant: str
    removed: int


def reset_by_login(login: str, *, tenant: str) -> ResetOutcome | None:
    """Сбросить вторую ступень по логину (команда с сервера); нет такой учётки — `None`."""
    with _managing("сбросить вторую ступень входа") as conn, conn.cursor() as cur:
        cur.execute(
            "select id, role, tenant_code from web_users"
            " where login = %s and tenant_code = %s and disabled_at is null",
            (login.strip().lower(), tenant),
        )
        строка = cur.fetchone()
        if строка is None:
            return None
        return ResetOutcome(
            user_id=str(строка[0]),
            role=str(строка[1]),
            tenant=str(строка[2]),
            removed=_reset(cur, str(строка[0])),
        )
