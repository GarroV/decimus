"""Clarification evidence commits with the finding, never as best-effort metadata."""

from dataclasses import asdict, replace

import pytest

from src.db.fingerprint import compute_fingerprint
from src.domain import add_finding, get_state, score, start_inspection
from src.domain.config import check_environment
from src.domain.engine import state_file
from src.domain.errors import ValidationError
from src.domain.models import Suggestion


def context():
    state = get_state(1)
    return {
        "run_id": state.run_id,
        "checklist_version": state.checklist_version,
        "code": "CLN05",
        "zone": "hot_kitchen",
        "photo_refs": ["synthetic-frame"],
        "clarifications": [{"question": "How many items?", "answer": "5"}],
    }


def add(**kwargs):
    return add_finding(
        1,
        "CLN05",
        "D1",
        "hot_kitchen",
        "Human description",
        words="Original observation\n5",
        photos=["synthetic-frame"],
        source="comment",
        reading_c=0,
        class_context=context(),
        **kwargs,
    )


def test_add_clarification_atomic_history_and_fingerprint_unchanged(domain_env):
    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    suggested = Suggestion("CLN05", "D1", "hot_kitchen", 0.7)
    finding = add(suggested=suggested)
    state = get_state(1)
    event = state.finding_history[0]
    assert event["kind"] == "clarification" and event["n"] == finding.n
    assert (
        event["run_id"] == state.run_id and event["clarifications"] == context()["clarifications"]
    )
    assert event["after"] == [asdict(finding)]
    assert finding.words == "Original observation\n5" and "How many" not in finding.words
    assert finding.source == "comment" and finding.reading_c == 0
    assert (
        finding.suggested_code,
        finding.suggested_level,
        finding.suggested_zone,
        finding.suggested_confidence,
    ) == (suggested.code, suggested.level, suggested.zone, suggested.confidence)
    result = score(1)
    assert compute_fingerprint(state, result, tenant_code=state.tenant) == compute_fingerprint(
        replace(state, finding_history=[]), result, tenant_code=state.tenant
    )


@pytest.mark.parametrize("failure", ["metadata", "commit"])
def test_failure_keeps_original_bytes_and_retry_has_one_finding(domain_env, monkeypatch, failure):
    from src.domain import findings

    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    path = state_file(1, check_environment())
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        if failure == "metadata":
            patch.setattr(
                findings, "remember_words", lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
            )
        else:
            real = findings._write_atomic

            def write(target, raw):
                if target == path:
                    raise OSError("disk")
                return real(target, raw)

            patch.setattr(findings, "_write_atomic", write)
        with pytest.raises(OSError):
            add()
    assert path.read_bytes() == before
    assert get_state(1).findings == [] and get_state(1).finding_history == []
    add()
    assert len(get_state(1).findings) == len(get_state(1).finding_history) == 1


@pytest.mark.parametrize(
    "key,value",
    [
        ("code", "CLN01"),
        ("run_id", "old"),
        ("photo_refs", []),
        ("zone", "hall"),
        ("checklist_version", "old"),
    ],
)
def test_context_binding_mismatch_does_not_write(domain_env, key, value):
    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    path = state_file(1, check_environment())
    before = path.read_bytes()
    with pytest.raises(ValidationError):
        add_finding(
            1,
            "CLN05",
            "D1",
            "hot_kitchen",
            "Human description",
            words="Original\n5",
            photos=["synthetic-frame"],
            class_context=context() | {key: value},
        )
    assert path.read_bytes() == before
