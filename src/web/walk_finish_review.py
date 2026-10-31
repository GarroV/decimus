"""Read-only miniapp review of the current run; the engine owns every score."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from src.domain import get_state, score
from src.domain.errors import DomainError
from src.domain.models import Inspection


def revision(inspection: Inspection) -> str:
    """Detect edits since the auditor reviewed this run without exposing its content."""
    content = json.dumps(asdict(inspection), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def review(chat_id: int, lang: str) -> dict[str, Any] | None:
    inspection = get_state(chat_id)
    if inspection is None:
        return None
    before = revision(inspection)
    result = score(chat_id)
    current = get_state(chat_id)
    if current is None or revision(current) != before:
        raise DomainError("Проверка изменилась во время подготовки итога")
    return {
        "run_id": inspection.run_id,
        "revision": before,
        "summary": {
            "pct": result.pct,
            "grade": result.grade,
            "label": result.label(lang),
            "counts": result.counts,
            "total": len(inspection.findings),
        },
    }
