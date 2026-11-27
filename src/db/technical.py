"""Previous technical snapshot of the same unit, space and checklist, within reach."""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from psycopg.types.json import Json

from .config import check_environment
from .inspection_edits import Editor, record_edit
from .pool import connection
from .reach import Reach, require_reach
from .reading import reading


class TechnicalReviewRefused(ValueError):
    """A reviewer must explicitly reconfirm current evidence before acceptance."""


_EVIDENCE_SQL = """
select f.n, f.code, f.level, f.zone,
    coalesce((select t.text from translations t where t.entity_type = 'finding'
      and t.entity_id = f.id and t.field = 'text' and t.lang = i.speech_lang), ''),
    array(select p.telegram_file_id from photos p where p.finding_id = f.id
      and p.purged_at is null order by p.telegram_file_id)
from findings f join inspections i on i.id = f.inspection_id
where i.id = %(inspection)s and i.tenant_code = %(tenant)s
order by f.n
"""


def reconcile(
    cur: Any, inspection_id: str, tenant: str, snapshot: dict[str, Any] | None
) -> dict[str, Any] | None:
    """A changed/deleted linked observation requires a fresh human confirmation."""
    if not snapshot or not snapshot.get("enabled"):
        return snapshot
    result = copy.deepcopy(snapshot)
    cur.execute(_EVIDENCE_SQL, {"inspection": inspection_id, "tenant": tenant})
    current = {
        row[0]: dict(n=row[0], code=row[1], level=row[2], zone=row[3], text=row[4], photos=row[5])
        for row in cur.fetchall()
    }
    for check in result.get("checks", []):
        candidates = {
            n: item
            for n, item in current.items()
            if item["zone"] == check["zone"]
            and item["code"] in check["item_codes"]
            and item["text"].strip()
            and item["photos"]
        }
        if check.get("status") not in {"issue", "recorded"}:
            if check.get("status") == "pending":
                check["candidate_evidence"] = list(candidates.values())
            continue
        evidence = check.get("finding_evidence") or []
        valid = bool(evidence) and all(
            item.get("n") in candidates
            and all(
                candidates[item["n"]][field] == item.get(field)
                for field in ("code", "level", "zone", "text")
            )
            and sorted(candidates[item["n"]]["photos"]) == sorted(item.get("photos") or [])
            for item in evidence
        )
        if not valid:
            check.update(
                status="pending",
                terminal=False,
                finding_numbers=[],
                review_invalidated=True,
                candidate_evidence=list(candidates.values()),
            )
    rows = result.get("checks", [])
    result["checked"] = sum(row.get("status") != "pending" for row in rows)
    result["pending"] = len(rows) - result["checked"]
    result["required_pending"] = sum(
        row.get("required", False) and row.get("status") == "pending" for row in rows
    )
    return result


def assert_ready(cur: Any, inspection_id: str, tenant: str) -> None:
    """Called under the same row lock as acceptance and finding revisions."""
    cur.execute(
        "select technical_snapshot from inspections where id = %s and tenant_code = %s",
        (inspection_id, tenant),
    )
    row = cur.fetchone()
    state = reconcile(cur, inspection_id, tenant, row[0]) if row else None
    if state and state.get("required_pending"):
        from .errors import AcceptError

        raise AcceptError(
            "Технические контрольные точки требуют повторного подтверждения после правки записей",
            code="accept_technical_pending",
        )


def confirm_review(
    inspection_id: str,
    *,
    tenant: str,
    check_id: str,
    zone: str,
    status: str,
    reason: str,
    editor: Editor,
    finding_number: int | None = None,
) -> None:
    """Confirm a checkpoint on review; preserve the original visit snapshot otherwise."""
    ident = str(uuid.UUID(inspection_id))
    if status not in {"ok", "na", "issue", "recorded"} or len(reason) > 1000:
        raise TechnicalReviewRefused()
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "select technical_snapshot from inspections where id = %s and tenant_code = %s "
            "and status = 'draft' and retracted_at is null for update",
            (ident, tenant),
        )
        head = cur.fetchone()
        if head is None:
            raise TechnicalReviewRefused()
        state = reconcile(cur, ident, tenant, head[0])
        if not state:
            raise TechnicalReviewRefused()
        point = next(
            (r for r in state.get("checks", []) if r["id"] == check_id and r["zone"] == zone), None
        )
        if not point:
            raise TechnicalReviewRefused()
        before = copy.deepcopy(
            next(row for row in head[0]["checks"] if row["id"] == check_id and row["zone"] == zone)
        )
        _review_point(
            point, status=status, reason=reason, editor=editor, finding_number=finding_number
        )
        for row in state["checks"]:
            row.pop("candidate_evidence", None)
        state["checked"] = sum(row.get("status") != "pending" for row in state["checks"])
        state["pending"] = len(state["checks"]) - state["checked"]
        state["required_pending"] = sum(
            row.get("required", False) and row.get("status") == "pending" for row in state["checks"]
        )
        cur.execute(
            "update inspections set technical_snapshot = %s where id = %s and tenant_code = %s",
            (Json(state), ident, tenant),
        )
        record_edit(
            cur,
            inspection_id=ident,
            finding_id=None,
            tenant=tenant,
            editor=editor,
            kind="technical",
            changes={"technical_checkpoint": {"old": before, "new": point}},
        )
        conn.commit()


def _review_point(
    point: dict[str, Any],
    *,
    status: str,
    reason: str,
    editor: Editor,
    finding_number: int | None,
) -> None:
    """Apply the same explicit evidence rules as the auditor's ordinary walk."""
    if status == "na" and not reason.strip():
        raise TechnicalReviewRefused()
    if status == "ok" and (point.get("requires_photo") or point.get("status") == "issue"):
        raise TechnicalReviewRefused()
    selected = []
    if status in {"issue", "recorded"}:
        selected = [r for r in point.get("candidate_evidence", []) if r["n"] == finding_number]
        if not selected:
            raise TechnicalReviewRefused()
        level = selected[0]["level"]
        if status == "issue" and level not in {"D1", "D2", "D3"}:
            raise TechnicalReviewRefused()
        if status == "recorded" and (level != "D0" or point.get("kind") != "info"):
            raise TechnicalReviewRefused()
    point.update(
        status=status,
        terminal=True,
        reason=reason.strip(),
        review_invalidated=False,
        finding_evidence=selected,
        finding_numbers=[r["n"] for r in selected],
        confirmed_at=datetime.now(UTC).isoformat(),
        confirmed_by=editor.login,
        confirmed_in="review",
    )


@dataclass(frozen=True)
class PreviousTechnical:
    inspection_id: str
    inspection_date: date
    snapshot: dict[str, Any] | None


_PREVIOUS_SQL = """
select p.id, p.inspection_date, p.technical_snapshot
from inspections i
join units u on u.id = i.unit_id
join inspections p on p.unit_id = i.unit_id
    and p.tenant_code = i.tenant_code and p.checklist_code = i.checklist_code
where i.id = %(inspection)s
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
  and (%(reader)s::text <> 'HQ' or i.tenant_code = 'HQ' or i.status <> 'finalized')
  and p.status = 'finalized' and p.retracted_at is null
  and (p.inspection_date, p.pushed_at, p.id) < (i.inspection_date, i.pushed_at, i.id)
order by p.inspection_date desc, p.pushed_at desc, p.id desc
limit %(limit)s
"""


def history_snapshots(
    inspection_id: str, *, reach: Reach, limit: int = 5
) -> tuple[PreviousTechnical, ...]:
    """At most five prior accepted visits, including visits without technical data."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ValueError("technical history limit")
    params = {
        **require_reach(reach).params(),
        "inspection": str(uuid.UUID(inspection_id)),
        "limit": limit,
    }
    with reading("предыдущее техническое состояние") as conn:
        rows = conn.execute(_PREVIOUS_SQL, params).fetchall()
    return tuple(PreviousTechnical(str(row[0]), row[1], row[2]) for row in rows)
