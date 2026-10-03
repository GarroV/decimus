"""Привязка бота к учётке через веб (D286): выпуск ссылки, погашение, привязка, отвязка.

Ядро держится тремя свойствами, и каждое проверяет свой тест:

* ссылка одноразовая — погашение и привязка идут одной транзакцией, а повтор
  упирается в `used_at is null`;
* ссылка короткоживущая — срок в строке (`LINK_TTL`), сверка на стороне базы;
* привязка ведёт в пространство УЧЁТКИ — тенант берётся из `web_users`, а не из
  бота, ссылки или чего-то, что пришло снаружи.

Отказ базы — `AccessError`, а не `None`: «не пускаем» и «не смогли посмотреть» —
разные ответы, и бот обязан их различать (задача 11).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from .web_access import _connected

#: Сколько живёт ссылка привязки: её открывают сразу, с той же страницы.
LINK_TTL = timedelta(minutes=10)
#: Метка deep-link: `t.me/<бот>?start=link-<токен>`. Telegram пропускает в
#: `start` до 64 знаков `A-Za-z0-9_-`.
LINK_PREFIX = "link-"
#: 24 байта случайности — 32 знака urlsafe; с меткой — 37 из 64 допустимых.
_TOKEN_BYTES = 24

_EXPIRE_PREVIOUS_SQL = """
    update bot_link_tokens set used_at = now()
     where user_id = %s and used_at is null
"""
_ISSUE_SQL = """
    insert into bot_link_tokens (fingerprint, user_id, expires_at)
    values (%s, %s, now() + %s) returning expires_at
"""
_SPEND_SQL = """
    update bot_link_tokens t set used_at = now(), used_by = %(tg)s
      from web_users u
     where t.fingerprint = %(fp)s and t.used_at is null and t.expires_at > now()
       and u.id = t.user_id and u.disabled_at is null
 returning t.user_id
"""
_TAKEN_BY_OTHER_SQL = """
    select 1 from bot_bindings
     where telegram_id = %s and unbound_at is null and user_id <> %s
"""
_UNBIND_USER_SQL = """
    update bot_bindings set unbound_at = now() where user_id = %s and unbound_at is null
"""
_BIND_SQL = "insert into bot_bindings (telegram_id, user_id) values (%s, %s)"
_RESOLVE_BY_TELEGRAM_SQL = """
    select b.telegram_id, u.id, u.login, u.tenant_code, b.bound_at
      from bot_bindings b join web_users u on u.id = b.user_id
     where b.unbound_at is null and u.disabled_at is null and b.telegram_id = %s
"""
_RESOLVE_BY_USER_SQL = """
    select b.telegram_id, u.id, u.login, u.tenant_code, b.bound_at
      from bot_bindings b join web_users u on u.id = b.user_id
     where b.unbound_at is null and u.disabled_at is null and u.id = %s
"""


@dataclass(frozen=True)
class IssuedLink:
    """Выпущенная ссылка. `token` уходит в адрес и больше нигде не живёт."""

    token: str
    expires_at: datetime


@dataclass(frozen=True)
class Binding:
    """Живая привязка: какой Telegram ID, к какой учётке и в каком пространстве."""

    telegram_id: int
    user_id: str
    login: str
    tenant: str
    bound_at: datetime


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_link(user_id: str) -> IssuedLink:
    """Новая ссылка. Прежние неиспользованные гаснут: живой остаётся одна."""
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    with _connected("выпустить ссылку привязки бота") as conn, conn.cursor() as cur:
        cur.execute(_EXPIRE_PREVIOUS_SQL, (user_id,))
        cur.execute(_ISSUE_SQL, (_fingerprint(token), user_id, LINK_TTL))
        row = cur.fetchone()
    if row is None:
        # `insert ... returning` без строки не бывает; молча выдать ссылку,
        # которой нет в базе, значило бы обмануть человека на экране.
        raise RuntimeError("ссылка привязки не записалась")
    return IssuedLink(token=token, expires_at=row[0])


def redeem(token: str, *, telegram_id: int) -> Binding | None:
    """Погасить ссылку и привязать Telegram ID. `None` — один ответ на все отказы.

    Нет такой, использована, просрочена, учётка отключена, этот Telegram уже
    привязан к другой учётке — снаружи неразличимы: различие подсказало бы
    перехватившему ссылку, что именно не так.
    """
    if not token:
        return None
    with _connected("привязать бота") as conn, conn.cursor() as cur:
        cur.execute(_SPEND_SQL, {"tg": telegram_id, "fp": _fingerprint(token)})
        row = cur.fetchone()
        if row is None:
            return None
        user_id = str(row[0])
        cur.execute(_TAKEN_BY_OTHER_SQL, (telegram_id, user_id))
        if cur.fetchone() is not None:
            # Ссылка при этом погашена: перепривязка чужого Telegram не
            # срабатывает и со второй попытки той же ссылкой.
            return None
        cur.execute(_UNBIND_USER_SQL, (user_id,))
        cur.execute(_BIND_SQL, (telegram_id, user_id))
    return resolve(telegram_id)


def resolve(telegram_id: int) -> Binding | None:
    """Живая привязка этого Telegram ID к живой учётке — или `None`."""
    return _one(_RESOLVE_BY_TELEGRAM_SQL, telegram_id, "опознать Telegram ID")


def binding_of(user_id: str) -> Binding | None:
    """Живая привязка учётки — для страницы «Пользователи»."""
    return _one(_RESOLVE_BY_USER_SQL, user_id, "прочитать привязку бота")


def unbind(user_id: str) -> bool:
    """Отвязать бота от учётки. `False` — живой привязки не было."""
    with _connected("отвязать бота") as conn, conn.cursor() as cur:
        cur.execute(_UNBIND_USER_SQL, (user_id,))
        return cur.rowcount > 0


def _one(sql: str, value: object, зачем: str) -> Binding | None:
    with _connected(зачем) as conn, conn.cursor() as cur:
        cur.execute(sql, (value,))
        row = cur.fetchone()
    if row is None:
        return None
    return Binding(
        telegram_id=int(row[0]),
        user_id=str(row[1]),
        login=str(row[2]),
        tenant=str(row[3]),
        bound_at=row[4],
    )
