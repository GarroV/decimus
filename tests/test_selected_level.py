"""Selected-item severity reads one complete pinned criterion; no provider is called."""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from src.domain import start_inspection
from src.recognize.client import ModelAnswer
from src.recognize.config import RecognizeSettings

ROOT = Path(__file__).resolve().parent.parent
CFG = RecognizeSettings("synthetic", "synthetic", "", 1.0, 0.0, 5, "unused")


def method(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, criteria: str) -> Path:
    data = tmp_path / "synthetic-method"
    shutil.copytree(ROOT / "tests/methodology", data)
    with (data / "checklist.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    for row in rows:
        if row["id"] == "CLN05":
            row["levels"] = "D1;D2;D3"
    with (data / "checklist.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (data / "criteria.md").write_text(criteria)
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data))
    return data


def test_full_selected_criteria_over_old_cap_and_pinned_edition(
    domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.recognize.selected_level import prepare_selected_level

    section = "Synthetic criterion. " * 500 + "TAIL CONDITION MUST SURVIVE"
    data = method(tmp_path, monkeypatch, "## CLN05\n" + section + "\n## CLN06\nOther criterion\n")
    original = start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    (data / "criteria.md").write_text("## CLN05\nNew synthetic criterion\n")
    request = prepare_selected_level(
        1,
        code="CLN05",
        zone="hot_kitchen",
        words="Auditor facts",
        photo_refs=(),
        photos=(),
        selection_revision="selection-1",
        settings=CFG,
    )
    assert section in request.ask.question
    assert "Other criterion" not in request.ask.question
    assert request.context["checklist_version"] == original.checklist_version
    assert request.levels == ("D1", "D2", "D3")


def test_need_fact_is_not_a_ready_level_and_context_changes_with_facts(
    domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.recognize.selected_level import finish_selected_level, prepare_selected_level

    method(tmp_path, monkeypatch, "## CLN05\nSynthetic alternatives, ask the missing count.\n")
    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    first = prepare_selected_level(
        1,
        code="CLN05",
        zone="hot_kitchen",
        words="Incomplete facts",
        photo_refs=(),
        photos=(),
        selection_revision="selection-1",
        settings=CFG,
    )
    reply = finish_selected_level(
        first, ModelAnswer({"level": "D1", "need_fact": "How many?", "reason": "Count missing"})
    )
    assert reply["status"] == "needs_fact" and reply["level"] is None
    assert reply["provisional_level"] == "D1" and reply["need_fact"] == "How many?"
    second = prepare_selected_level(
        1,
        code="CLN05",
        zone="hot_kitchen",
        words="New explicit count",
        photo_refs=(),
        photos=(),
        selection_revision="selection-2",
        settings=CFG,
    )
    assert second.context["facts_key"] != first.context["facts_key"]
    assert second.context["selection_revision"] == "selection-2"


@pytest.mark.parametrize(
    "payload",
    [
        {"level": "D1", "reason": "missing question field"},
        {"level": "D1", "need_fact": None, "reason": "malformed"},
        {"level": "OTHER", "need_fact": "", "reason": "wrong enum"},
    ],
)
def test_malformed_answer_is_not_success(payload) -> None:
    from src.recognize.level import level_from

    assert level_from(ModelAnswer(payload), ["D1", "D2"]) is None


def test_criteria_resource_cap_rejects_instead_of_truncating() -> None:
    from src.recognize.errors import RecognizeError
    from src.recognize.level import MAX_CRITERIA_CHARS, level_request

    with pytest.raises(RecognizeError):
        level_request(
            "Auditor fact",
            code="SYN01",
            levels=["D1", "D2"],
            criteria="x" * (MAX_CRITERIA_CHARS + 1),
            lang="en",
            settings=CFG,
        )
