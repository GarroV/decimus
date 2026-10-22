"""Уведомления в приложении (#1129, D604, D614): запись событий и чтение своих.

Одна общая таблица `notifications` (`0090`): кому, вид события, адрес внутри
приложения и параметры текста. Текст не хранится — по виду его берёт экран из
словаря на языке человека. Наружу из приложения не уходит ничего: ни почты, ни
Telegram (§7 глобальных правил).

**Запись — внутри чужой транзакции.** `notify` принимает курсор того, кто
совершает событие, и ничего не коммитит: уведомление ложится атомарно с самим
переходом — откатился переход, откатилось и оно. Событие предписания пишет
администратор истории (`prescriptions_write`), поэтому `notify` и поиск адресатов
работают на его курсоре.

**Чтение — только своё.** Каждый запрос чтения и отметки несёт `user_id`, чью
учётку определила сессия веба; чужая строка не читается и не отмечается ни по
номеру, ни по адресу. Построчной политики у таблицы нет (`0090`): граница —
условие в самом запросе, и тест держит её.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from .config import check_environment
from .errors import AccessError
from .pool import connection

#: Сколько строк отдаёт один показ списка, если вызывающий не назвал меньше.
MAX_LIST = 100

_INSERT_SQL = """
insert into notifications (user_id, kind, link, params)
values (%s::uuid, %s, %s, %s::jsonb)
"""

#: Все, кто сейчас работает под ролью, в пространстве (отключённые не в счёт).
_USERS_BY_ROLE_SQL = """
select id::text from web_users
 where role = %s and tenant_code = %s and disabled_at is null
 order by login
"""

_USER_BY_LOGIN_SQL = """
select id::text from web_users
 where login = %s and tenant_code = %s and disabled_at is null
"""

_LIST_SQL = """
select id, kind, link, params, created_at, read_at
  from notifications
 where user_id = %(user)s::uuid
   and (not %(unread_only)s or read_at is null)
 order by created_at desc, id desc
 limit %(limit)s
"""

_COUNT_SQL = "select count(*) from notifications where user_id = %s::uuid and read_at is null"

_MARK_SQL = """
update notifications set read_at = now()
 where id = %s and user_id = %s::uuid and read_at is null
"""

_MARK_ALL_SQL = """
update notifications set read_at = now() where user_id = %s::uuid and read_at is null
"""

_MARK_LINK_SQL = """
update notifications set read_at = now()
 where link = %s and user_id = %s::uuid and read_at is null
"""


@dataclass(frozen=True)
class Notification:
    """Одно уведомление в том виде, в каком его рисует экран: вид, адрес и параметры, не текст."""

    id: int
    kind: str
    link: str
    params: dict[str, Any]
    created_at: datetime
    read_at: datetime | None

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


@contextmanager
def _connected(зачем: str) -> Iterator[psycopg.Connection[Any]]:
    """Роль приложения. Наружу — тип исключения драйвера, не текст (в нём бывает DSN)."""
    settings = check_environment()
    try:
        with connection(settings.dsn) as conn:
            yield conn
    except psycopg.Error as exc:
        raise AccessError(f"Не удалось {зачем} ({type(exc).__name__})") from exc


def _uuid_or_none(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


# ── Запись: в чужой транзакции ───────────────────────────────────────────


def notify(
    cur: psycopg.Cursor[Any],
    users: Iterable[str],
    kind: str,
    link: str,
    params: dict[str, Any] | None = None,
) -> int:
    """Положить уведомление каждому из `users` на курсоре вызывающего. Ничего не коммитит.

    `users` — ключи учёток веба; повторы схлопываются, пустой набор — ничего не
    пишется. `link` — путь внутри приложения (`/osb?id=…`), `params` — только
    то, из чего экран соберёт текст на своём языке. Возвращает число записанных
    строк. Отказ базы идёт вверх как есть: вызывающий откатывает свою транзакцию.
    """
    получатели = list(dict.fromkeys(str(u) for u in users))
    if not получатели:
        return 0
    данные = json.dumps(params or {}, ensure_ascii=False)
    for user in получатели:
        cur.execute(_INSERT_SQL, (user, kind, link, данные))
    return len(получатели)


def users_with_role(cur: psycopg.Cursor[Any], role: str, *, tenant: str) -> list[str]:
    """Ключи работающих учёток роли в пространстве — адресаты события «всем ОСБ»."""
    cur.execute(_USERS_BY_ROLE_SQL, (role, tenant))
    return [str(row[0]) for row in cur.fetchall()]


def user_by_login(cur: psycopg.Cursor[Any], login: str, *, tenant: str) -> str | None:
    """Ключ работающей учётки по логину в пространстве. Нет такой — `None`, а не отказ."""
    cur.execute(_USER_BY_LOGIN_SQL, (login, tenant))
    row = cur.fetchone()
    return None if row is None else str(row[0])


# ── Чтение и отметка: только своё ────────────────────────────────────────


def list_for(user: str, limit: int = MAX_LIST, *, unread_only: bool = False) -> list[Notification]:
    """Уведомления учётки, новые сверху. Чужих здесь нет: условие — `user_id`."""
    ключ = _uuid_or_none(user)
    if ключ is None:
        return []
    предел = max(1, min(int(limit), MAX_LIST))
    with _connected("прочитать уведомления") as conn, conn.cursor() as cur:
        cur.execute(_LIST_SQL, {"user": ключ, "unread_only": unread_only, "limit": предел})
        return [
            Notification(
                id=int(row[0]),
                kind=str(row[1]),
                link=str(row[2]),
                params=dict(row[3]),
                created_at=row[4],
                read_at=row[5],
            )
            for row in cur.fetchall()
        ]


def unread_count(user: str) -> int:
    """Сколько у учётки непрочитанного."""
    ключ = _uuid_or_none(user)
    if ключ is None:
        return 0
    with _connected("посчитать уведомления") as conn, conn.cursor() as cur:
        cur.execute(_COUNT_SQL, (ключ,))
        row = cur.fetchone()
    return 0 if row is None else int(row[0])


def mark_read(user: str, notification_id: int) -> bool:
    """Отметить свою строку прочитанной. `False` — строки нет, она чужая или уже прочитана."""
    ключ = _uuid_or_none(user)
    if ключ is None:
        return False
    with _connected("отметить уведомление") as conn, conn.cursor() as cur:
        cur.execute(_MARK_SQL, (int(notification_id), ключ))
        return cur.rowcount > 0


def mark_read_by_link(user: str, link: str) -> int:
    """Отметить прочитанными все свои непрочитанные с этим адресом. Возвращает их число."""
    ключ = _uuid_or_none(user)
    if ключ is None:
        return 0
    with _connected("отметить уведомления") as conn, conn.cursor() as cur:
        cur.execute(_MARK_LINK_SQL, (link, ключ))
        return cur.rowcount


def mark_all_read(user: str) -> int:
    """Отметить прочитанными все свои непрочитанные. Возвращает их число."""
    ключ = _uuid_or_none(user)
    if ключ is None:
        return 0
    with _connected("отметить уведомления") as conn, conn.cursor() as cur:
        cur.execute(_MARK_ALL_SQL, (ключ,))
        return cur.rowcount
