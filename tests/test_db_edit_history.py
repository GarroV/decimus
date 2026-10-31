"""Edit evidence survives push and a later run without altering the push fingerprint."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from conftest import requires_db
from db_harness import accept_pushed
from test_domain_edit_history import source

from src.db.fingerprint import compute_fingerprint
from src.db.push import push_inspection
from src.db.queries import get_inspection
from src.db.reach import own_reach
from src.domain import edit_finding, get_state, score, start_inspection

pytestmark = requires_db


def test_edit_history_push_read_and_new_run_preserve_original(
    domain_env: Path, db_env: str
) -> None:
    finding = source()
    inspection = get_state(1)
    edit_finding(1, finding.n, text="Synthetic changed", photos=["frame-b"], reading_c=0)
    event = get_state(1).finding_history[0]
    split_state = get_state(1)
    result = score(1)
    without_history = replace(split_state, finding_history=[])
    assert compute_fingerprint(split_state, result, tenant_code=inspection.tenant) == (
        compute_fingerprint(without_history, result, tenant_code=inspection.tenant)
    )
    ident = push_inspection(1)
    assert push_inspection(1) == ident
    accept_pushed(ident)
    start_inspection(1, unit="Next run", kind="planned", report_lang="ru")
    assert get_state(1).finding_history == []
    detail = get_inspection(ident, reach=own_reach("default"))
    assert detail is not None
    assert detail.inspection.finding_history == [event]
    assert detail.inspection.finding_history[0]["before"]["words"] == "synthetic words"
    assert len(detail.findings) == 1
    assert detail.inspection.pct == result.pct
