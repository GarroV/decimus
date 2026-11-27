"""Actual archive roundtrip preserves explicit technical observations."""

from __future__ import annotations

import json
from dataclasses import asdict

import psycopg
import pytest
from conftest import requires_db
from db_harness import set_retraction_env

from src.db.accept import accept_inspection
from src.db.errors import AcceptError
from src.db.inspection_edits import Editor
from src.db.push import push_inspection
from src.db.queries import get_inspection
from src.db.reach import own_reach
from src.db.technical import TechnicalReviewRefused, assert_ready, confirm_review, history_snapshots
from src.domain import add_finding, get_state, start_inspection
from src.report.letters import state_json

pytestmark = requires_db
REVIEWER = Editor(user_id="13600000-0000-0000-0000-000000000001", login="reviewer", role="admin")


def test_archive_roundtrip_keeps_frozen_technical_evidence(domain_env, db_env, monkeypatch):
    frozen = {
        "enabled": True,
        "checks": [
            {
                "id": "TC001",
                "zone": "dining",
                "item_codes": ["CLN05"],
                "status": "ok",
                "title_ru": "Крепление исправно",
                "title_en": "Mounting works",
                "finding_numbers": [],
            }
        ],
        "total": 1,
        "checked": 1,
        "pending": 0,
        "required_pending": 0,
    }
    monkeypatch.setattr("src.domain.technical.snapshot", lambda *args, **kwargs: frozen)
    start_inspection(136001, unit="Белград-1", kind="planned", report_lang="ru")
    inspection_id = push_inspection(136001)
    restored = get_inspection(inspection_id, reach=own_reach("HQ"), include_on_review=True)
    assert restored is not None
    assert restored.inspection.technical_snapshot == frozen
    assert json.loads(state_json(restored, lang="en"))["domain"]["technical_snapshot"] == frozen
    assert restored.inspection.pct == 100
    assert restored.findings == ()
    assert push_inspection(136001) == inspection_id


def test_review_edit_invalidates_link_and_requires_explicit_reconfirmation(
    domain_env, db_env, pg_dsn, monkeypatch
):
    set_retraction_env(db_env, monkeypatch)
    start_inspection(136002, unit="Белград-1", kind="planned", report_lang="ru")
    add_finding(136002, code="CLN05", level="D1", zone="hot_kitchen", text="Дефект", photos=["p1"])
    finding = get_state(136002).findings[0]
    frozen = {
        "enabled": True,
        "checks": [
            {
                "id": "TC001",
                "zone": "hot_kitchen",
                "item_codes": ["CLN05"],
                "required": True,
                "status": "issue",
                "title_ru": "Оборудование",
                "title_en": "Equipment",
                "finding_numbers": [finding.n],
                "finding_evidence": [asdict(finding)],
            }
        ],
        "required_pending": 0,
    }
    monkeypatch.setattr("src.domain.technical.snapshot", lambda *args, **kwargs: frozen)
    inspection_id = push_inspection(136002)
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "update translations set text = %s where entity_type = 'finding' and field = 'text' "
            "and entity_id in (select id from findings where inspection_id = %s)",
            ("Уточнённый дефект", inspection_id),
        )
        conn.commit()
    changed = get_inspection(inspection_id, reach=own_reach("HQ"), include_on_review=True)
    assert changed.inspection.technical_snapshot["required_pending"] == 1
    assert changed.inspection.technical_snapshot["checks"][0]["status"] == "pending"
    with pytest.raises(AcceptError) as refusal:
        accept_inspection(inspection_id, tenant="HQ", actor="reviewer")
    assert refusal.value.code == "accept_technical_pending"
    with pytest.raises(TechnicalReviewRefused):
        confirm_review(
            inspection_id,
            tenant="HQ",
            check_id="TC001",
            zone="hot_kitchen",
            status="na",
            reason="",
            editor=REVIEWER,
        )
    confirm_review(
        inspection_id,
        tenant="HQ",
        check_id="TC001",
        zone="hot_kitchen",
        status="issue",
        reason="",
        editor=REVIEWER,
        finding_number=finding.n,
    )
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        assert_ready(cur, inspection_id, "HQ")
    # The same transaction retains the original proof and the new answer.
    with psycopg.connect(pg_dsn) as conn:
        entry = conn.execute(
            "select finding_id, login, role, kind, changes from inspection_edits "
            "where inspection_id = %s order by id desc limit 1",
            (inspection_id,),
        ).fetchone()
    assert entry[:4] == (None, "reviewer", "admin", "technical")
    change = entry[4]["technical_checkpoint"]
    assert change["old"]["finding_evidence"][0]["text"] == "Дефект"
    assert change["new"]["finding_evidence"][0]["text"] == "Уточнённый дефект"
    assert change["new"]["confirmed_by"] == "reviewer"
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")
    accept_inspection(inspection_id, tenant="HQ", actor="reviewer")
    accepted = get_inspection(inspection_id, reach=own_reach("HQ"))
    frozen_accepted = accepted.inspection.technical_snapshot
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update photos set purged_at = now() where inspection_id = %s", (inspection_id,)
        )
        conn.commit()
    historical = get_inspection(inspection_id, reach=own_reach("HQ"))
    assert historical.inspection.technical_snapshot == frozen_accepted
    assert historical.inspection.technical_snapshot["checks"][0]["status"] == "issue"


def test_matrix_history_is_bounded_in_space_and_keeps_visits_without_data(
    domain_env, db_env, monkeypatch
):
    set_retraction_env(db_env, monkeypatch)
    frozen = {
        "enabled": True,
        "checks": [
            {
                "id": "TC001",
                "zone": "dining",
                "item_codes": ["CLN05"],
                "required": True,
                "status": "ok",
                "title_ru": "Крепление",
                "title_en": "Mounting",
                "finding_numbers": [],
            }
        ],
        "required_pending": 0,
    }
    monkeypatch.setattr(
        "src.domain.technical.snapshot",
        lambda chat_id, **kwargs: {"enabled": False} if chat_id == 136004 else frozen,
    )
    ids = []
    for chat_id, visit_date in [
        (136003, "2026-01-01"),
        (136004, "2026-06-01"),
        (136005, "2026-11-26"),
    ]:
        start_inspection(
            chat_id, unit="Белград-1", kind="planned", report_lang="ru", date=visit_date
        )
        ident = push_inspection(chat_id)
        ids.append(ident)
        if chat_id != 136005:
            accept_inspection(ident, tenant="HQ", actor="reviewer")
    history = history_snapshots(ids[-1], reach=own_reach("HQ"))
    assert [row.inspection_id for row in history] == list(reversed(ids[:2]))
    assert history[0].snapshot is None
    assert history[1].snapshot["checks"][0]["status"] == "ok"
    assert history_snapshots(ids[-1], reach=own_reach("OTHER")) == ()
