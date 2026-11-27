"""Activation preserves scoring, rejects stale inputs and keeps pinned runs on rollback."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp_checklist_harness import build_edition

from src.domain import get_state, start_inspection
from src.domain.checklist_store import published_dir
from src.domain.config import DATA_FILES
from src.domain.state import finish_inspection
from src.domain.technical import TechnicalRefused, confirm, snapshot
from src.domain.version import compose
from src.mcp.checklist import Store, current_version, publish, read_journal
from src.mcp.errors import ChecklistError
from tools.technical_activate import stage


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Store, Path, str]:
    data = tmp_path / "data"
    build_edition(data, name="activation", day="2026-11-01")
    initial = Store(root=tmp_path / "store", live=data)
    old = current_version(initial)
    store = replace(initial, live=initial.root / "current")
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    monkeypatch.setenv("AUDIT_DATA_DIR", str(store.live))
    source = tmp_path / "technical.json"
    source.write_text(
        json.dumps(
            {
                "version": 1,
                "checks": [
                    {
                        "id": "TC001",
                        "item_codes": ["CLN01"],
                        "zones": ["fridge"],
                        "title_ru": "Контроль поверхности",
                        "title_en": "Surface check",
                        "required": True,
                    }
                ],
            }
        )
    )
    return store, source, old


def test_activation_and_rollback_preserve_live_and_finished_runs(
    domain_env: Path, setup: tuple[Store, Path, str]
) -> None:
    store, source, old = setup
    start_inspection(901, unit="Sample-1", kind="planned", report_lang="en", auditor="Test")
    original = {p.name: p.read_bytes() for p in published_dir(store, old).iterdir() if p.is_file()}
    journal = read_journal(store)
    assert stage(store, source, expected=old)["status"] == "validated"
    assert read_journal(store) == journal
    outcome = stage(store, source, expected=old, write=True)
    assert outcome["accepted"]
    new = str(outcome["version"])
    assert current_version(store) == old
    candidate = published_dir(store, new)
    assert all(
        (candidate / name).read_bytes() == value
        for name, value in original.items()
        if name != "checklist_version.txt"
    )
    assert {
        p.name: p.read_bytes() for p in published_dir(store, old).iterdir() if p.is_file()
    } == original
    # Runtime 22056208 hashes this exact old DATA_FILES set; it rejects the new edition.
    old_files = tuple(name for name in DATA_FILES if name != "technical_checks.json")
    assert compose(candidate, old_files) != new
    assert compose(published_dir(store, old), old_files) == old
    publish(store, tenant="HQ", version=new, expected_current=old)
    assert stage(store, source, expected=new, write=True)["status"] == "unchanged"
    assert snapshot(901)["checks"] == []
    start_inspection(902, unit="Sample-1", kind="planned", report_lang="en", auditor="Test")
    run = get_state(902)
    assert run
    assert snapshot(902)["required_pending"] == 1
    publish(store, tenant="HQ", version=old, expected_current=new)
    assert snapshot(902)["required_pending"] == 1
    with pytest.raises(TechnicalRefused, match="pending"):
        finish_inspection(902, run.run_id, datetime.now(UTC))
    confirm(902, run_id=run.run_id, check_id="TC001", zone="fridge", status="ok")
    finish_inspection(902, run.run_id, datetime.now(UTC))
    sealed = snapshot(902)
    start_inspection(903, unit="Sample-1", kind="planned", report_lang="en", auditor="Test")
    assert snapshot(903)["checks"] == []
    assert snapshot(902) == sealed


def test_stale_activation_and_publication_do_not_replace_newer_work(
    setup: tuple[Store, Path, str],
) -> None:
    store, source, old = setup
    outcome = stage(store, source, expected=old, write=True)
    with pytest.raises(ChecklistError) as stale:
        stage(store, source, expected=old, write=True)
    assert stale.value.refusal == "edit_stale"
    assert current_version(store) == old
    with pytest.raises(ChecklistError) as stale:
        publish(store, tenant="HQ", version=str(outcome["version"]), expected_current="outdated")
    assert stale.value.refusal == "edit_stale"
    assert current_version(store) == old


def test_invalid_manifest_never_changes_published_edition(setup: tuple[Store, Path, str]) -> None:
    store, source, old = setup
    data = json.loads(source.read_text())
    data["checks"][0]["item_codes"] = ["UNKNOWN"]
    source.write_text(json.dumps(data))
    journal = read_journal(store)
    with pytest.raises(TechnicalRefused):
        stage(store, source, expected=old, write=True)
    assert current_version(store) == old
    assert read_journal(store) == journal


def test_demo_history_has_no_invented_confirmations_and_live_walk_is_enabled(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools import seed_open_demo as seed

    monkeypatch.setenv("AUDIT_DATA_DIR", str(seed.seed_demo.DEMO_DATA_DIR))
    visit = seed.VISITS[0]
    unit = next(unit for unit in seed.UNITS if unit.name == visit.unit)
    seed._build_historical(904, visit, unit, set(), None)
    historical = get_state(904)
    assert historical and not historical.technical_enabled
    assert snapshot(904)["checks"] == []
    seed._walk(None)
    for chat in (seed.WALK_CHAT, seed.WALK_CHAT_RU):
        current = get_state(chat)
        assert current and current.technical_enabled
        assert current.checklist_version != historical.checklist_version
        assert snapshot(chat)["required_pending"] == 2
    assert snapshot(904)["checks"] == []
