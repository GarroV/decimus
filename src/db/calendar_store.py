"""Доступ человека к Google Календарю и события срока отчёта в базе (D740, D741, #1590).

Ключ продления хранится зашифрованным (`secret_crypto`: AES-256-GCM, ключ шифрования —
`SECRETS_KEY` в окружении, имя записи в связанных данных — `calendar:<user_id>`: шифртекст
одного человека не подложить под другого). Открытое значение живёт только в памяти на время
вызова Google и не попадает ни в журнал, ни в тексты отказов.

Читает и пишет роль приложения: веб подключает и отключает, бот ведёт события.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg

from src.domain.journal import DOOR_BOT

from . import journals, secret_crypto
from .errors import DbError
from .web_access import _connected

logger = logging.getLogger(__name__)

#: Окно, в котором проверки ещё ведут события: старше — срок давно прошёл, а перенос такой
#: проверки в будущее случается редко и ловится при следующем сдвиге даты.
WORK_WINDOW_DAYS = 21


def _secret_name(user_id: str) -> str:
    return f"calendar:{user_id}"


@dataclass(frozen=True)
class Grant:
    """Подключение человека без ключа: что показать на экране и с кем разговаривать."""

    user_id: str
    google_email: str
    scope: str
    problem: str | None


@dataclass(frozen=True)
class Candidate:
    """Проверка, по которой должно стоять событие, и что стоит сейчас."""

    inspection_id: str
    user_id: str
    unit: str
    inspection_date: date
    ui_lang: str
    event_id: str | None
    event_due: date | None
    event_title: str | None


@dataclass(frozen=True)
class Orphan:
    """Событие, чьей проверки больше не видно роли приложения: снята (отклонена)."""

    inspection_id: str
    user_id: str
    event_id: str


_GRANT_SQL = "select user_id, google_email, scope, problem from calendar_grants where user_id = %s"

_SAVE_SQL = """
insert into calendar_grants (user_id, google_email, scope, refresh_ciphertext)
values (%s, %s, %s, %s)
on conflict (user_id) do update
set google_email = excluded.google_email, scope = excluded.scope,
    refresh_ciphertext = excluded.refresh_ciphertext, connected_at = now(),
    problem = null, problem_at = null
"""

#: Кто сейчас ведёт события: у человека есть рабочее подключение (не мёртвое — мёртвое ждёт
#: переподключения, а временный сбой повторяется) и живая привязка бота,
#: проверка — полевая проверка УК, не снятая. Событие, если есть, — рядом (`left join`).
_CANDIDATES_SQL = """
select i.id, b.user_id, u.name, i.inspection_date, i.ui_lang,
       e.event_id, e.due_date, e.title
  from inspections i
  join units u on u.id = i.unit_id
  join bot_bindings b on b.telegram_id = i.chat_id and b.unbound_at is null
  join calendar_grants g on g.user_id = b.user_id
                        and (g.problem is null or g.problem <> all(%(dead)s))
  left join calendar_events e on e.inspection_id = i.id
 where i.tenant_code = 'HQ' and i.origin = 'field' and i.retracted_at is null
   and i.inspection_date >= %(since)s
 order by i.inspection_date, i.id
"""

_ORPHANS_SQL = """
select e.inspection_id, e.user_id, e.event_id
  from calendar_events e
 where not exists (select 1 from inspections i where i.id = e.inspection_id)
"""


def save_grant(user_id: str, *, google_email: str, scope: str, refresh_token: str) -> None:
    """Записать (или заменить) подключение: ключ — только шифртекстом."""
    blob = secret_crypto.encrypt(_secret_name(user_id), refresh_token)
    with _connected("сохранить подключение календаря") as conn, conn.cursor() as cur:
        cur.execute(_SAVE_SQL, (user_id, google_email, scope, blob))


def grant_of(user_id: str) -> Grant | None:
    """Подключение человека или `None`; ключа здесь нет."""
    with _connected("прочитать подключение календаря") as conn, conn.cursor() as cur:
        cur.execute(_GRANT_SQL, (user_id,))
        row = cur.fetchone()
    return None if row is None else _grant(row)


def refresh_token_of(user_id: str) -> str | None:
    """Открытый ключ продления — только для вызова Google. Не открылся — `SecretCryptoError`."""
    with _connected("прочитать ключ календаря") as conn, conn.cursor() as cur:
        cur.execute("select refresh_ciphertext from calendar_grants where user_id = %s", (user_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return secret_crypto.decrypt(_secret_name(user_id), bytes(row[0]))


def delete_grant(user_id: str) -> bool:
    """Стереть подключение и события-записи человека. `False` — подключения не было."""
    with _connected("снять подключение календаря") as conn, conn.cursor() as cur:
        cur.execute("delete from calendar_events where user_id = %s", (user_id,))
        cur.execute("delete from calendar_grants where user_id = %s", (user_id,))
        return cur.rowcount > 0


def mark_problem(user_id: str, code: str) -> None:
    """Запомнить код сбоя Google: экран скажет «переподключите», задача пропустит человека."""
    with _connected("записать сбой календаря") as conn, conn.cursor() as cur:
        cur.execute(
            "update calendar_grants set problem = %s, problem_at = now() where user_id = %s",
            (code, user_id),
        )


def clear_problem(user_id: str) -> None:
    """Календарь снова ответил — пометка сбоя снимается."""
    with _connected("снять сбой календаря") as conn, conn.cursor() as cur:
        cur.execute(
            "update calendar_grants set problem = null, problem_at = null "
            "where user_id = %s and problem is not null",
            (user_id,),
        )


def candidates(*, since: date, dead: tuple[str, ...]) -> list[Candidate]:
    """Проверки окна, по которым ведутся события (уже с тем, что стоит в календаре).

    `dead` — коды сбоя, после которых подключение ждёт переподключения человеком.
    """
    with _connected("прочитать проверки для календаря") as conn, conn.cursor() as cur:
        cur.execute(_CANDIDATES_SQL, {"since": since, "dead": list(dead)})
        rows = cur.fetchall()
    return [
        Candidate(str(r[0]), str(r[1]), str(r[2]), r[3], str(r[4] or ""), r[5], r[6], r[7])
        for r in rows
    ]


def orphans() -> list[Orphan]:
    """События снятых проверок: роль приложения снятую проверку не видит вовсе (0010)."""
    with _connected("прочитать события снятых проверок") as conn, conn.cursor() as cur:
        cur.execute(_ORPHANS_SQL)
        return [Orphan(str(r[0]), str(r[1]), str(r[2])) for r in cur.fetchall()]


def events_of(user_id: str) -> list[Orphan]:
    """Все события человека — убрать из календаря перед отключением."""
    with _connected("прочитать события календаря") as conn, conn.cursor() as cur:
        cur.execute(
            "select inspection_id, user_id, event_id from calendar_events where user_id = %s",
            (user_id,),
        )
        return [Orphan(str(r[0]), str(r[1]), str(r[2])) for r in cur.fetchall()]


def remember_event(
    inspection_id: str, user_id: str, *, event_id: str, due: date, title: str
) -> None:
    """Записать, что в календаре стоит это событие (создано или сдвинуто)."""
    with _connected("записать событие календаря") as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into calendar_events (inspection_id, user_id, event_id, due_date, title)
            values (%s, %s, %s, %s, %s)
            on conflict (inspection_id) do update
            set user_id = excluded.user_id, event_id = excluded.event_id,
                due_date = excluded.due_date, title = excluded.title, synced_at = now()
            """,
            (inspection_id, user_id, event_id, due, title),
        )


def forget_event(inspection_id: str) -> None:
    """Событие из календаря убрано — запись о нём больше не нужна."""
    with _connected("снять запись о событии календаря") as conn, conn.cursor() as cur:
        cur.execute("delete from calendar_events where inspection_id = %s", (inspection_id,))


def journal_problem(user_id: str, code: str, *, inspection_id: str | None = None) -> None:
    """Строка в журнал действий: сбой календаря. Отказ базы — в журнал процесса, не наружу."""
    try:
        with _connected("прочитать роль для журнала календаря") as conn, conn.cursor() as cur:
            cur.execute("select role, tenant_code from web_users where id = %s", (user_id,))
            row = cur.fetchone()
        if row is None:
            return
        journals.record_action(
            user_id=user_id,
            role=str(row[0]),
            tenant=str(row[1]),
            action="calendar_sync",
            target=f"inspection={inspection_id}" if inspection_id else "",
            outcome=code,
            ip=None,
            credential=None,
            door=DOOR_BOT,
        )
    except (DbError, psycopg.Error):
        logger.warning("календарь: строка в журнал действий не записана", exc_info=True)


def _grant(row: tuple[Any, ...]) -> Grant:
    return Grant(str(row[0]), str(row[1]), str(row[2]), row[3])
