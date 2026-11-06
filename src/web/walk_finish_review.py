"""Read-only miniapp review of the current run; the engine owns every score."""

from __future__ import annotations

from typing import Any

from src.domain import get_state, score
from src.domain.errors import DomainError
from src.domain.revision import revision


def review(chat_id: int, lang: str) -> dict[str, Any] | None:
    inspection = get_state(chat_id)
    if inspection is None:
        return None
    before = revision(inspection)
    result = score(chat_id)
    from src.report import ReportError, build_letter_notes

    try:
        letter = build_letter_notes(chat_id)
    except ReportError as exc:
        raise DomainError("Обратная связь для итога сейчас недоступна") from exc
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
            "feedback_skipped": list(letter.feedback_skipped),
            "feedback_lang": letter.feedback_lang,
        },
    }
