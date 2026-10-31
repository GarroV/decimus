"""Clarification provenance uses the existing history column and push fingerprint."""

from dataclasses import replace

from conftest import requires_db
from db_harness import accept_pushed
from test_domain_clarifications import add

from src.db.fingerprint import compute_fingerprint
from src.db.push import push_inspection
from src.db.queries import get_inspection
from src.db.reach import own_reach
from src.domain import get_state, score, start_inspection

pytestmark = requires_db


def test_clarification_push_roundtrip_keeps_chain_and_original_words(domain_env, db_env):
    start_inspection(1, unit="Synthetic", kind="planned", report_lang="ru")
    finding = add()
    state = get_state(1)
    event = state.finding_history[0]
    result = score(1)
    assert compute_fingerprint(state, result, tenant_code=state.tenant) == compute_fingerprint(
        replace(state, finding_history=[]), result, tenant_code=state.tenant
    )
    ident = push_inspection(1)
    assert push_inspection(1) == ident
    accept_pushed(ident)
    start_inspection(1, unit="Next run", kind="planned", report_lang="ru")
    assert get_state(1).finding_history == []
    detail = get_inspection(ident, reach=own_reach("default"))
    assert detail is not None
    assert detail.inspection.finding_history == [event]
    assert event["after"][0]["words"] == finding.words
    assert event["clarifications"] == [{"question": "How many items?", "answer": "5"}]
