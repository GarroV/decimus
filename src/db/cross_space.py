"""Журнал действий человека УК в пространстве партнёра (спека «Администрирование»).

`record` пишет на ПЕРЕДАННОМ подключении и не коммитит: дверь действия зовёт
его до своего коммита, и строка журнала живёт ровно столько, сколько само
действие. Своего подключения здесь нет намеренно — второе подключение
закоммитило бы журнал отдельно от действия.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from src.domain.permissions import Actor, require_action
from src.domain.tenants import canonical_tenant

_INSERT_SQL = """
    insert into cross_space_actions
        (actor_web_user_id, actor_tenant, object_tenant, action_code, object_ref)
    values (%s, %s, %s, %s, %s)
"""


@dataclass(frozen=True)
class Entry:
    """Строка журнала: кто, из какого пространства, в чьём, что и над чем."""

    actor_web_user_id: str
    actor_tenant: str
    object_tenant: str
    action_code: str
    object_ref: str


def entry_for(actor: Actor, *, object_tenant: str, action: str, object_ref: str) -> Entry | None:
    """Строка журнала для действия — или `None`, если пространство своё.

    Пишет её вызывающий — и только если действие СОСТОЯЛОСЬ (строка сменилась):
    холостой вызов следа «кто, что, когда» не оставляет.
    """
    require_action(action)
    кто = canonical_tenant(actor.tenant)
    чьё = canonical_tenant(object_tenant)
    if кто == чьё:
        return None
    if not actor.user_id:
        raise ValueError(
            "Действие в чужом пространстве без учётки: журналу некого записать. "
            "Так действует только человек УК с учёткой веба"
        )
    return Entry(actor.user_id, кто, чьё, action, object_ref)


def record(conn: psycopg.Connection[Any], entry: Entry | None) -> None:
    """Дописать строку журнала на подключении действия. `None` — писать нечего."""
    if entry is None:
        return
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            (
                entry.actor_web_user_id,
                entry.actor_tenant,
                entry.object_tenant,
                entry.action_code,
                entry.object_ref,
            ),
        )
