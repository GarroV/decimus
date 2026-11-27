"""Technical checkpoint history: explicit observations, never inferred good results."""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from src.domain.models import localized

STATUSES = {"pending", "ok", "issue", "na", "recorded"}


def snapshot_for_export(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Export observations, excluding transient candidates offered by the review form."""
    result = copy.deepcopy(snapshot)
    for check in result.get("checks", []):
        check.pop("candidate_evidence", None)
    return result


def checkpoint_rows(snapshot: dict[str, Any] | None, *, lang: str) -> list[dict[str, Any]]:
    """Read the frozen wording, without consulting a newer checklist edition."""
    if not snapshot or not snapshot.get("enabled"):
        return []
    rows = snapshot.get("checks")
    if not isinstance(rows, list):
        return []
    result = []
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("zone"):
            continue
        status = raw.get("status")
        result.append(
            {
                **raw,
                "title": localized(raw, "title", lang, fall_back=("en", "ru"))
                or str(raw.get("title") or ""),
                "guidance": localized(raw, "guidance", lang, fall_back=("en", "ru"))
                or str(raw.get("guidance") or ""),
                "status": status if status in STATUSES else "pending",
                "reason": str(raw.get("reason") or ""),
                "finding_numbers": raw.get("finding_numbers") or [],
            }
        )
    return result


def present(
    snapshot: dict[str, Any] | None,
    *,
    lang: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare by stable id + physical zone; missing and NA never mean fixed."""
    rows = checkpoint_rows(snapshot, lang=lang)
    before = {(r["id"], r["zone"]): r for r in checkpoint_rows(previous, lang=lang)}
    for row in rows:
        old = before.get((row["id"], row["zone"]))
        row["previous_status"] = old["status"] if old else None
        current = row["status"]
        prior = row["previous_status"]
        row["change"] = (
            "fixed"
            if prior == "issue" and current == "ok"
            else "new_issue"
            if prior == "ok" and current == "issue"
            else "persists"
            if prior == current == "issue"
            else "unchanged"
            if prior == current and current in {"ok", "recorded"}
            else "uncompared"
        )
    counts = Counter(row["status"] for row in rows)
    return {
        "enabled": bool(snapshot and snapshot.get("enabled")),
        "rows": rows,
        "total": len(rows),
        "checked": len(rows) - counts["pending"],
        "pending": counts["pending"],
        "issues": counts["issue"],
        "na": counts["na"],
        "comparison_available": bool(before),
    }


def history_matrix(
    columns: list[dict[str, Any]], *, lang: str, zone_order: list[str] | None = None
) -> dict[str, Any]:
    """Union checkpoints across dated inspections; an absent cell stays absent."""
    points: dict[tuple[str, str], dict[str, Any]] = {}
    indexed = []
    for column in columns:
        rows = checkpoint_rows(column.get("snapshot"), lang=lang)
        indexed.append({(row["id"], row["zone"]): row for row in rows})
        for row in rows:
            # Later wording wins in the overview, while each report retains its own wording.
            points[(row["id"], row["zone"])] = row
    result = []
    for key, point in points.items():
        cells = []
        for lookup in indexed:
            observed = lookup.get(key)
            cells.append(
                {
                    "status": observed["status"] if observed else "absent",
                    "reason": observed["reason"] if observed else "",
                    "finding_numbers": observed["finding_numbers"] if observed else [],
                    "title": observed["title"] if observed else "",
                }
            )
        result.append(
            {
                "id": key[0],
                "zone": key[1],
                "title": point["title"],
                "guidance": point["guidance"],
                "cells": cells,
            }
        )
    zones = dict.fromkeys([*(zone_order or []), *(row["zone"] for row in result)])
    groups = [
        {"zone": zone, "rows": [row for row in result if row["zone"] == zone]}
        for zone in zones
        if any(row["zone"] == zone for row in result)
    ]
    return {"columns": columns, "rows": result, "groups": groups}
