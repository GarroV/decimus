"""Frozen technical evidence and change since the previous inspection in its scope."""

from __future__ import annotations

from typing import Any

from src.db.errors import DbError
from src.db.models import InspectionDetail
from src.db.reach import Reach
from src.db.technical import PreviousTechnical, history_snapshots
from src.db.technical import confirm_review as confirm_review
from src.report.technical import history_matrix, present


def card_context(detail: InspectionDetail, *, lang: str, reach: Reach) -> dict[str, Any]:
    snapshot = detail.inspection.technical_snapshot
    previous = None
    history: tuple[PreviousTechnical, ...] = ()
    known = True
    if snapshot and snapshot.get("enabled"):
        try:
            history = history_snapshots(detail.inspection.id, reach=reach)
            previous = history[0] if history else None
        except DbError:
            known = False
    return {
        "technical": {
            **present(snapshot, lang=lang, previous=previous.snapshot if previous else None),
            "previous": previous,
            "previous_known": known,
            "matrix": history_matrix(
                [
                    *[
                        {
                            "inspection_id": row.inspection_id,
                            "date": row.inspection_date,
                            "snapshot": row.snapshot,
                        }
                        for row in reversed(history)
                    ],
                    {
                        "inspection_id": detail.inspection.id,
                        "date": detail.inspection.inspection_date,
                        "snapshot": snapshot,
                    },
                ],
                lang=lang,
                zone_order=list(detail.by_zone),
            ),
        }
    }
