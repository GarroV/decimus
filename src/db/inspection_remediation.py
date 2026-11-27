"""Состояния исправлений находок, решения проверяющего и неизменяемая история."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from .errors import DbError
from .reach import Reach, require_reach
from .reading import reading


class RemediationRefused(ValueError):
    """Нельзя выполнить действие над текущим состоянием исправления."""


@dataclass(frozen=True)
class State:
    finding_id: str
    status: str = "open"
    revision: int = 0


@dataclass(frozen=True)
class Event:
    kind: str
    actor: str
    reason: str
    created_at: datetime
    revision: int


@dataclass(frozen=True)
class EventPage:
    entries: tuple[Event, ...] = ()
    more: bool = False


_ITEM_SQL = """
select f.id, coalesce(r.status, 'open'), coalesce(r.revision, 0), i.tenant_code
from findings f join inspections i on i.id = f.inspection_id
join units u on u.id = i.unit_id
left join inspection_remediation r on r.finding_id = f.id
where i.id = %(inspection)s and f.level in ('D1', 'D2', 'D3')
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""


def states(inspection_id: str, *, reach: Reach, as_admin: bool = False) -> dict[str, State]:
    """Пункты исходного отчёта, включая открытые без записи состояния; ничего не создаёт."""
    params = {**require_reach(reach).params(), "inspection": str(uuid.UUID(inspection_id))}
    with reading("исправления проверки", as_admin=as_admin) as conn:
        rows = conn.execute(_ITEM_SQL, params).fetchall()
    return {str(row[0]): State(str(row[0]), row[1], row[2]) for row in rows}


def events(
    inspection_id: str,
    finding_id: str,
    *,
    reach: Reach,
    as_admin: bool = False,
    before: int | None = None,
) -> EventPage:
    """Последние решения и изменения материалов выбранного пункта."""
    # Право на исходную находку проверяется тем же запросом, что у списка.
    if finding_id not in states(inspection_id, reach=reach, as_admin=as_admin):
        raise RemediationRefused("missing")
    with reading("история исправления", as_admin=as_admin) as conn:
        rows = conn.execute(
            "select kind, actor, reason, created_at, revision from inspection_remediation_events "
            "where finding_id = %s and (%s::integer is null or revision < %s) "
            "order by revision desc limit 51",
            (finding_id, before, before),
        ).fetchall()
    return EventPage(
        tuple(Event(row[0], row[1], row[2], row[3].astimezone(UTC), row[4]) for row in rows[:50]),
        len(rows) > 50,
    )


def check_item(inspection_id: str, finding_id: str, *, reach: Reach) -> None:
    state = states(inspection_id, reach=reach).get(finding_id)
    if state is None or state.status == "confirmed":
        raise RemediationRefused("closed" if state else "missing")


def transition(
    inspection_id: str,
    finding_id: str,
    *,
    reach: Reach,
    actor: str,
    action: str,
    revision: int,
    reason: str = "",
) -> None:
    """Передать участником либо подтвердить/вернуть проверяющим; версия защищает доказательства."""
    if action not in {"submit", "confirm", "return", "reopen"}:
        raise RemediationRefused("action")
    if action in {"return", "reopen"} and not (0 < len(reason.strip()) <= 5000):
        raise RemediationRefused("reason")
    if not actor.strip() or len(actor) > 200:
        raise RemediationRefused("actor")
    params = {**require_reach(reach).params(), "inspection": str(uuid.UUID(inspection_id))}
    finding_id = str(uuid.UUID(finding_id))
    with reading("изменить исправление", as_admin=action != "submit") as conn:
        conn.execute("select inspection_remediation_lock(%s, %s)", (inspection_id, finding_id))
        row = next(
            (
                row
                for row in conn.execute(_ITEM_SQL, params).fetchall()
                if str(row[0]) == finding_id
            ),
            None,
        )
        if row is None:
            raise RemediationRefused("missing")
        if row[2] != revision:
            raise RemediationRefused("conflict")
        if action != "submit" and row[3] != reach.tenant:
            raise RemediationRefused("review")
        expected = {
            "submit": "open",
            "confirm": "submitted",
            "return": "submitted",
            "reopen": "confirmed",
        }
        if row[1] != expected[action]:
            raise RemediationRefused("state")
        if revision == 0:
            raise RemediationRefused("evidence")
        conn.execute("select set_config('decimus.remediation_actor', %s, true)", (actor,))
        conn.execute("select set_config('decimus.remediation_reason', %s, true)", (reason.strip(),))
        result = conn.execute(
            "update inspection_remediation set status = %s, revision = revision + 1 "
            "where finding_id = %s and revision = %s",
            (
                {"submit": "submitted", "confirm": "confirmed", "return": "open", "reopen": "open"}[
                    action
                ],
                finding_id,
                revision,
            ),
        )
        if result.rowcount != 1:
            raise DbError("Исправление не обновлено")
        conn.commit()
