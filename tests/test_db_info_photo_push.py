"""Push retains photo-only evidence without manufacturing a textual answer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.db.push import _push_info
from src.domain import get_state, start_inspection
from src.domain.models import InfoAnswer


def test_push_inserts_blank_caption_only_when_there_are_photos(domain_env: Path):
    start_inspection(793010706, unit="Synthetic photo answer", kind="planned", report_lang="ru")
    inspection = replace(
        get_state(793010706),
        info={
            "INF08": InfoAnswer(code="INF08", text="", photos=["real-ref-a", "real-ref-b"]),
            "INF01": InfoAnswer(code="INF01", text="", photos=[]),
        },
    )
    statements = []

    class Cursor:
        def execute(self, sql, params):
            statements.append((sql, params))

        def fetchone(self):
            return ("saved-info-id",)

    _push_info(Cursor(), inspection, inspection_id="inspection-id")
    assert len(statements) == 3
    assert statements[0][1]["code"] == "INF08" and statements[0][1]["text"] == ""
    assert [entry[1][-1] for entry in statements[1:]] == ["real-ref-a", "real-ref-b"]
