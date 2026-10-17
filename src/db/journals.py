"""Журнал входов и журнал действий (D462, `0067`): запись и чтение.

**Пишет роль приложения, читает схема.** Запись — прямой `insert` (прав на `update`,
`delete` и `select` у роли нет): задним числом строку не поправить. Чтение — только
функциями базы, которые определяют зрителя по токену его живой сессии и сами
решают, чьи записи ему видны: человек — свои входы, главный админ — все входы и
журнал действий. Фильтр «по человеку», названный вызовом, права не расширяет.

**Запись журнала не должна ронять то, что журналируется.** Отказ базы при записи
уходит в журнал процесса громко (`logger.exception`), но вход или действие не
отменяет: вход уже состоялся, а действие уже выполнено, и объяснять человеку
«не записалось» нечем. Тихим сбой при этом не бывает — только в строках журнала
процесса, их смотрит владелец при разборе.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.domain.journal import (
    DOOR_WEB,
    MAX_ACTION,
    RESULT_BAD_PASSWORD,
    RESULT_FROZEN,
    RESULT_RATE_LIMITED,
    RESULT_UNKNOWN,
    truncate_user_agent,
)

from .errors import DbError
from .web_access import _connected

logger = logging.getLogger(__name__)

#: Сколько строк отдаёт экран за раз. Больше схема всё равно не вернёт (1000).
DEFAULT_LIMIT = 200

_RECORD_LOGIN_SQL = """
    insert into login_journal (user_id, ip, user_agent, method, result, session_id)
    values (%(user)s, %(ip)s, %(ua)s, %(method)s, %(result)s, %(session)s)
"""

#: Какой исход у неудачной попытки с этим логином: нет такого, заморожен или неверный пароль.
_LOGIN_STATE_SQL = "select id, disabled_at is not null from web_users where login = %s"
#: Почта уникальна только среди живых (F-031, `0075`): у замороженной и живой
#: учётки она может совпасть, и тогда исход входа — про живую.
_EMAIL_STATE_SQL = """
    select id, disabled_at is not null
      from web_users
     where email = %s
     order by disabled_at is not null, id
     limit 1
"""

_RECORD_ACTION_SQL = """
    insert into action_journal
        (user_id, role, tenant_code, door, credential, ip, action, target, outcome)
    values (%(user)s, %(role)s, %(tenant)s, %(door)s, %(credential)s, %(ip)s,
            %(action)s, %(target)s, %(outcome)s)
"""

_READ_LOGINS_SQL = "select * from login_journal_read(%s, %s, %s, %s, %s)"
_READ_ACTIONS_SQL = "select * from action_journal_read(%s, %s, %s, %s, %s)"
_PEOPLE_SQL = "select * from journal_people(%s)"
_PURGE_SQL = "select purge_journals()"


@dataclass(frozen=True)
class LoginEntry:
    """Строка журнала входов так, как её показывает экран."""

    id: int
    at: datetime
    user_id: str | None
    login: str | None
    ip: str | None
    user_agent: str | None
    method: str
    result: str
    session_id: str | None


@dataclass(frozen=True)
class ActionEntry:
    """Строка журнала действий так, как её показывает экран."""

    id: int
    at: datetime
    user_id: str
    login: str
    role: str
    door: str
    credential: str | None
    ip: str | None
    action: str
    target: str
    outcome: str


def failure_result(login: str | None = None, *, email: str | None = None) -> tuple[str | None, str]:
    """Учётка и исход неудачной попытки: заморожена, неверный пароль или такой нет.

    Ищется по логину (пароль) или по почте (Google).
    """
    if login:
        sql, key = _LOGIN_STATE_SQL, login.strip().lower()
    elif email:
        sql, key = _EMAIL_STATE_SQL, email.strip().lower()
    else:
        return None, RESULT_UNKNOWN
    with _connected("определить исход входа") as conn, conn.cursor() as cur:
        cur.execute(sql, (key,))
        row = cur.fetchone()
    if row is None:
        return None, RESULT_UNKNOWN
    return str(row[0]), RESULT_FROZEN if row[1] else RESULT_BAD_PASSWORD


def record_login(
    *,
    method: str,
    result: str,
    user_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    session_id: str | None = None,
) -> None:
    """Дописать попытку входа. Отказ базы — в журнал процесса, вход он не отменяет."""
    try:
        with _connected("записать вход в журнал") as conn, conn.cursor() as cur:
            cur.execute(
                _RECORD_LOGIN_SQL,
                {
                    "user": user_id,
                    "ip": ip,
                    "ua": truncate_user_agent(user_agent),
                    "method": method,
                    "result": result,
                    "session": session_id,
                },
            )
    except DbError:
        logger.exception("журнал входов: запись не прошла (способ %s, исход %s)", method, result)


def _record_rate_limited(
    *, method: str, ip: str | None, user_agent: str | None, login: str | None, email: str | None
) -> None:
    """Отказ по частоте — одним вызовом функции базы, одна строка на адрес и способ за 10 минут.

    Запертый ключ ограничитель отсекает дёшево; запись для него не должна стать дорогой и
    не должна раздувать журнал, поэтому дедупликация и поиск учётки — на стороне базы.
    """
    try:
        with _connected("записать отказ по частоте") as conn, conn.cursor() as cur:
            cur.execute(
                "select record_rate_limited_login(%s, %s, %s, %s, %s)",
                (login, email, ip, truncate_user_agent(user_agent), method),
            )
    except DbError:
        logger.exception("журнал входов: отказ по частоте не записан (способ %s)", method)


def record_failed_login(
    *,
    method: str,
    ip: str | None,
    user_agent: str | None,
    login: str | None = None,
    email: str | None = None,
    result: str | None = None,
) -> None:
    """Неудачная попытка: учётку и исход (заморожен / пароль / неизвестен) определяет база.

    `result` задаёт исход сам (отказ по частоте, закрытый способ) — учётка при этом
    всё равно ищется, чтобы запись легла на человека.
    """
    if result == RESULT_RATE_LIMITED:
        _record_rate_limited(method=method, ip=ip, user_agent=user_agent, login=login, email=email)
        return
    try:
        user_id, найденный = failure_result(login, email=email)
    except DbError:
        logger.exception("журнал входов: исход попытки не определён (способ %s)", method)
        return
    record_login(
        method=method, result=result or найденный, user_id=user_id, ip=ip, user_agent=user_agent
    )


def record_action(
    *,
    user_id: str,
    role: str,
    tenant: str,
    action: str,
    target: str,
    outcome: str,
    ip: str | None,
    credential: str | None,
    door: str = DOOR_WEB,
) -> None:
    """Дописать действие админа. Отказ базы — в журнал процесса, действие он не отменяет."""
    try:
        with _connected("записать действие в журнал") as conn, conn.cursor() as cur:
            cur.execute(
                _RECORD_ACTION_SQL,
                {
                    "user": user_id,
                    "role": role,
                    "tenant": tenant,
                    "door": door,
                    "credential": credential,
                    "ip": ip,
                    "action": action[:MAX_ACTION],
                    "target": target,
                    "outcome": outcome[:40],
                },
            )
    except DbError:
        logger.exception("журнал действий: запись не прошла (действие %s)", action)


def read_logins(
    session_token: str,
    *,
    person: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[LoginEntry, ...]:
    """Журнал входов глазами зрителя: свои записи, у главного админа — все.

    `session_token` — токен живой сессии зрителя (как у `sign_out_everywhere`): по нему схема
    определяет, кто спрашивает, и в базе от него остаётся отпечаток. `end` не включается.
    """
    with _connected("прочитать журнал входов") as conn, conn.cursor() as cur:
        cur.execute(_READ_LOGINS_SQL, (session_token, person, start, end, limit))
        rows = cur.fetchall()
    return tuple(
        LoginEntry(
            id=int(r[0]),
            at=r[1],
            user_id=str(r[2]) if r[2] else None,
            login=r[3],
            ip=r[4],
            user_agent=r[5],
            method=str(r[6]),
            result=str(r[7]),
            session_id=str(r[8]) if r[8] else None,
        )
        for r in rows
    )


def read_actions(
    session_token: str,
    *,
    person: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[ActionEntry, ...]:
    """Журнал действий: только главный админ; остальным — пусто."""
    with _connected("прочитать журнал действий") as conn, conn.cursor() as cur:
        cur.execute(_READ_ACTIONS_SQL, (session_token, person, start, end, limit))
        rows = cur.fetchall()
    return tuple(
        ActionEntry(
            id=int(r[0]),
            at=r[1],
            user_id=str(r[2]),
            login=str(r[3]),
            role=str(r[4]),
            door=str(r[5]),
            credential=r[6],
            ip=r[7],
            action=str(r[8]),
            target=str(r[9]),
            outcome=str(r[10]),
        )
        for r in rows
    )


def journal_people(session_token: str) -> tuple[tuple[str, str], ...]:
    """Люди для фильтра «кто»: пары (номер, логин); не главному админу — пусто."""
    with _connected("прочитать людей журнала") as conn, conn.cursor() as cur:
        cur.execute(_PEOPLE_SQL, (session_token,))
        return tuple((str(r[0]), str(r[1])) for r in cur.fetchall())


def purge() -> int:
    """Убрать записи старше срока хранения (входы 180 дней, действия 365). Число убранных."""
    with _connected("убрать старые записи журналов") as conn, conn.cursor() as cur:
        cur.execute(_PURGE_SQL)
        row = cur.fetchone()
    return int(row[0]) if row else 0
