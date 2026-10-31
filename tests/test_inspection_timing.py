"""Inspection timing uses persisted server timestamps, never inferred metadata."""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.domain import add_finding, get_state, start_inspection
from src.domain.config import check_environment
from src.domain.engine import state_file


def test_start_is_persisted_across_mutation_reload_and_fresh_process(domain_env: Path) -> None:
    before = datetime.now(UTC)
    first = start_inspection(1, unit="Test", kind="planned", report_lang="ru")
    after = datetime.now(UTC)
    assert before <= first.started_at <= after
    assert first.finished_at is None
    add_finding(1, "CLN05", "D1", "hot_kitchen", "Текст")
    assert get_state(1).started_at == first.started_at
    output = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "from src.domain import get_state; s=get_state(1); "
            "print(s.run_id); print(s.started_at.isoformat())",
        ],
        env=os.environ,
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert output.decode().splitlines() == [first.run_id, first.started_at.isoformat()]
    second = start_inspection(1, unit="Test", kind="planned", report_lang="ru")
    assert second.run_id != first.run_id
    assert second.started_at >= first.started_at


def test_finish_freezes_and_unseal_preserves_confirmed_timestamp(domain_env: Path) -> None:
    from src.bot import sidecar
    from src.domain.state import finish_inspection
    from src.domain.timing import duration_seconds

    first = start_inspection(1, unit="Test", kind="planned", report_lang="ru")
    end = first.started_at + timedelta(seconds=125)
    finish_inspection(1, first.run_id, end)
    finish_inspection(1, first.run_id, end + timedelta(hours=1))
    assert get_state(1).finished_at == end
    assert duration_seconds(first.started_at, get_state(1).finished_at) == 125
    sidecar.unmark_handed_over(1)
    assert get_state(1).finished_at == end
    with pytest.raises(Exception, match="запуск"):
        finish_inspection(1, "another-run", end)


def test_old_inspection_has_no_guessed_timing(domain_env: Path) -> None:
    from src.domain.state import finish_inspection

    start_inspection(1, unit="Test", kind="planned", report_lang="ru")
    path = state_file(1, check_environment())
    raw = json.loads(path.read_text())
    raw["domain"].pop("started_at")
    path.write_text(json.dumps(raw))
    old = get_state(1)
    assert old.started_at is None and old.finished_at is None
    finish_inspection(1, old.run_id, datetime.now(UTC))
    assert get_state(1).finished_at is None


def test_duration_utc_dst_and_negative_intervals() -> None:
    from src.domain.timing import duration_seconds, parse_timestamp

    start = parse_timestamp("2026-10-25T02:59:00+02:00")
    end = parse_timestamp("2026-10-25T02:01:00+01:00")
    assert duration_seconds(start, end) == 120
    assert duration_seconds(None, end) is None
    assert duration_seconds(start, None) is None
    with pytest.raises(ValueError):
        duration_seconds(end, start)
    with pytest.raises(ValueError):
        parse_timestamp("2026-10-25T02:59:00")


def test_timing_is_excluded_from_push_fingerprint(domain_env: Path) -> None:
    from dataclasses import replace

    from src.db.fingerprint import compute_fingerprint
    from src.domain import score

    start = start_inspection(1, unit="Test", kind="planned", report_lang="ru")
    result = score(1)
    changed = replace(start, finished_at=start.started_at + timedelta(seconds=100))
    assert compute_fingerprint(start, result, tenant_code=start.tenant) == compute_fingerprint(
        changed, result, tenant_code=start.tenant
    )


def test_exact_start_clock_and_walk_contract(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.domain import state
    from src.web import walk

    stamp = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)
    monkeypatch.setattr(state, "utc_now", lambda: stamp)
    inspection = start_inspection(1, unit="Test", kind="planned", report_lang="ru")
    assert inspection.started_at == stamp
    payload = walk.build_walk(
        inspection, [], walk.PreviousOutcome(None), lang="ru", question=lambda _: None
    )
    assert payload["run_id"] == inspection.run_id
    assert payload["timing"]["started_at"] == stamp.isoformat()
    assert payload["timing"]["finished_at"] is None
    assert payload["timing"]["duration_seconds"] is None
