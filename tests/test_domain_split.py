"""Human split is a single persisted transition; rejected drafts leave no trace."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.domain import SOURCE_PHOTO, add_finding, get_state, score, start_inspection
from src.domain.config import check_environment
from src.domain.engine import state_file
from src.domain.errors import EngineError, ValidationError


def source():
    inspection = start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    finding = add_finding(
        1,
        "CLN05",
        "D1",
        "hot_kitchen",
        "Первое и второе наблюдение",
        photos=["frame-a", "frame-b"],
        words="synthetic original words",
        source=SOURCE_PHOTO,
    )
    return inspection, finding


def parts():
    from src.domain.split import SplitPart

    return [
        SplitPart("CLN05", "D1", "hot_kitchen", "Первое наблюдение", photos=("frame-a",)),
        SplitPart("CLN06", "D1", "hot_kitchen", "Второе наблюдение", photos=("frame-b",)),
    ]


def apply(
    inspection, finding, *, request_id="1" * 32, children=None, shared_photos=(), confirmed=True
):
    from src.domain.split import finding_revision, split_finding

    return split_finding(
        1,
        finding.n,
        children or parts(),
        expected_run_id=inspection.run_id,
        source_revision=finding_revision(finding),
        request_id=request_id,
        shared_photos=shared_photos,
        confirmed=confirmed,
    )


def test_split_keeps_explicit_children_and_source_history(domain_env: Path) -> None:
    inspection, finding = source()
    before_score = score(1)
    event = apply(inspection, finding)
    current = get_state(1)
    assert len(current.findings) == 2 and current.finding(finding.n) is None
    assert [f.photos for f in current.findings] == [["frame-a"], ["frame-b"]]
    assert all(not f.words and not f.suggested_code for f in current.findings)
    assert event["before"]["words"] == finding.words
    assert event["before"]["photos"] == finding.photos
    assert current.finding_history == [event]
    assert score(1).pct < before_score.pct  # only the existing engine computes this


def test_late_engine_failure_rolls_back_every_byte(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.domain import split

    inspection, finding = source()
    path = state_file(1, check_environment())
    before = path.read_bytes()
    real = split.run_audit
    count = 0

    def fail_second_child(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 3:
            raise EngineError("synthetic failure", code=1, command="add")
        return real(*args, **kwargs)

    monkeypatch.setattr(split, "run_audit", fail_second_child)
    with pytest.raises(EngineError):
        apply(inspection, finding)
    assert path.read_bytes() == before


def test_retry_after_reload_is_idempotent_and_changed_payload_conflicts(domain_env: Path) -> None:
    from src.domain.split import SplitConflict

    inspection, finding = source()
    event = apply(inspection, finding)
    assert get_state(1).finding_history == [event]
    assert apply(inspection, finding) == event
    changed = parts()
    changed[0] = replace(changed[0], text="Other text")
    with pytest.raises(SplitConflict):
        apply(inspection, finding, children=changed)
    assert len(get_state(1).finding_history) == 1 and len(get_state(1).findings) == 2


@pytest.mark.parametrize(
    "case", ["missing-photo", "foreign-photo", "shared-without-consent", "unconfirmed"]
)
def test_split_requires_explicit_photo_allocation_and_confirmation(
    domain_env: Path, case: str
) -> None:
    inspection, finding = source()
    children = parts()
    if case == "missing-photo":
        children[1] = replace(children[1], photos=())
    if case == "foreign-photo":
        children[1] = replace(children[1], photos=("foreign",))
    if case == "shared-without-consent":
        children[1] = replace(children[1], photos=("frame-a", "frame-b"))
    path = state_file(1, check_environment())
    before = path.read_bytes()
    with pytest.raises(ValidationError):
        apply(inspection, finding, children=children, confirmed=case != "unconfirmed")
    assert path.read_bytes() == before


def test_explicit_shared_photo_is_recorded_and_stale_revision_is_refused(domain_env: Path) -> None:
    from src.domain import edit_finding
    from src.domain.split import SplitConflict

    inspection, finding = source()
    edit_finding(1, finding.n, text="Changed concurrently")
    with pytest.raises(SplitConflict):
        apply(inspection, finding)
    current = get_state(1).finding(finding.n)
    children = parts()
    children[1] = replace(children[1], photos=("frame-a", "frame-b"))
    event = apply(inspection, current, children=children, shared_photos=("frame-a",))
    assert event["shared_photos"] == ["frame-a"]


def test_final_atomic_write_failure_does_not_remove_original(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.domain import split

    inspection, finding = source()
    path = state_file(1, check_environment())
    before = path.read_bytes()
    original = split._write_atomic

    def fail_commit(target, raw):
        if target == path:
            raise OSError("synthetic disk failure")
        return original(target, raw)

    monkeypatch.setattr(split, "_write_atomic", fail_commit)
    with pytest.raises(OSError):
        apply(inspection, finding)
    assert path.read_bytes() == before


def test_sealed_or_replaced_run_cannot_split(domain_env: Path) -> None:
    from src.bot import sidecar
    from src.domain.handover import HandedOverError
    from src.domain.split import SplitConflict

    inspection, finding = source()
    start_inspection(1, unit="replacement", kind="planned", report_lang="ru")
    with pytest.raises(SplitConflict):
        apply(inspection, finding)
    assert get_state(1).finding_history == []
    sidecar.mark_handed_over(1, 0)
    with pytest.raises(HandedOverError):
        apply(inspection, finding)
