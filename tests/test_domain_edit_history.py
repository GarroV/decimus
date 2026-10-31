"""Whole manual edit is one durable, replay-safe transition."""

from pathlib import Path

import pytest

from src.domain import add_finding, edit_finding, get_state, start_inspection
from src.domain.config import check_environment
from src.domain.engine import state_file
from src.domain.errors import EngineError
from src.domain.revisions import finding_revision


def source():
    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    return add_finding(
        1, "CLN05", "D1", "hot_kitchen", "Before", photos=["frame-a"], words="synthetic words"
    )


def test_complete_edit_replay_stale_and_restart(domain_env: Path):
    from src.domain.findings import EditConflict

    before = source()
    kwargs = dict(
        text="After",
        reading_c=0,
        photos=["frame-b"],
        source_revision=finding_revision(before),
        request_id="a" * 32,
    )
    after = edit_finding(1, before.n, **kwargs)
    state = get_state(1)
    event = state.finding_history[0]
    assert event["kind"] == "edit"
    assert event["before"]["photos"] == ["frame-a"]
    assert event["after"][0]["photos"] == ["frame-b"]
    assert after.reading_c == 0 and after.words == before.words
    assert edit_finding(1, before.n, **kwargs) == after
    assert len(get_state(1).finding_history) == 1
    with pytest.raises(EditConflict):
        edit_finding(1, before.n, text="Other", source_revision=finding_revision(before))
    with pytest.raises(EditConflict):
        edit_finding(1, before.n, **(kwargs | {"text": "Other"}))
    assert get_state(1).finding(before.n) == after


@pytest.mark.parametrize("failure", ["photo", "commit"])
def test_late_failure_leaves_source_byte_identical(domain_env: Path, monkeypatch, failure):
    from src.domain import findings

    before = source()
    path = state_file(1, check_environment())
    original = path.read_bytes()
    if failure == "photo":
        real = findings.run_audit

        def run(args, **kwargs):
            if args[0] == "photo" and "--remove=frame-a" in args:
                raise EngineError("synthetic", code=1, command="photo")
            return real(args, **kwargs)

        monkeypatch.setattr(findings, "run_audit", run)
        error = EngineError
    else:
        real_write = findings._write_atomic

        def write(target, raw):
            if target == path:
                raise OSError("synthetic disk failure")
            return real_write(target, raw)

        monkeypatch.setattr(findings, "_write_atomic", write)
        error = OSError
    with pytest.raises(error):
        edit_finding(
            1, before.n, text="After", reading_c=3, photos=["frame-b"], request_id="b" * 32
        )
    assert path.read_bytes() == original
    assert get_state(1).finding_history == []


def test_legacy_and_reading_only(domain_env: Path):
    from src.domain import set_reading

    record = source()
    edit_finding(1, record.n, text="Legacy")
    set_reading(1, record.n, 0)
    set_reading(1, record.n, None)
    state = get_state(1)
    assert state.finding(record.n).text == "Legacy"
    assert state.finding(record.n).reading_c is None
    assert len(state.finding_history) == 3
