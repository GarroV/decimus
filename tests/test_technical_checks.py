"""Technical confirmations are explicit, immutable after submission and bound to evidence."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.domain import add_finding, drop_finding, edit_finding, get_state, start_inspection
from src.domain.config import check_environment
from src.domain.engine import state_file
from src.domain.state import finish_inspection
from src.domain.technical import TechnicalConflict, TechnicalRefused, confirm, snapshot

DATA = Path(__file__).parent / "methodology"


@pytest.fixture
def technical_env(domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "technical-data"
    shutil.copytree(DATA, data)
    checks = [
        {
            "id": "TC001",
            "source_rows": [1],
            "item_codes": ["CLN05"],
            "zones": ["hot_kitchen"],
            "required": True,
            "title_ru": "Контроль поверхности",
            "title_en": "Surface check",
        },
        {
            "id": "TC002",
            "source_rows": [2],
            "item_codes": ["CLN05"],
            "zones": ["hot_kitchen"],
            "required": True,
            "title_ru": "Контроль другой поверхности",
            "title_en": "Another surface check",
        },
        {
            "id": "TC003",
            "source_rows": [3],
            "item_codes": ["INF09"],
            "zones": ["hot_kitchen"],
            "required": False,
            "kind": "info",
            "requires_photo": True,
            "title_ru": "Настройки",
            "title_en": "Settings",
        },
    ]
    (data / "technical_checks.json").write_text(json.dumps({"version": 1, "checks": checks}))
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data))
    start_inspection(77, unit="Sample-1", kind="planned", report_lang="en", auditor="Auditor")
    return data


def mark(ident: str = "TC001", **kwargs: object) -> None:
    inspection = get_state(77)
    assert inspection is not None
    confirm(77, run_id=inspection.run_id, check_id=ident, zone="hot_kitchen", **kwargs)


def test_explicit_completion_and_na_reason(technical_env: Path) -> None:
    inspection = get_state(77)
    assert inspection is not None
    assert snapshot(77)["required_pending"] == 2
    with pytest.raises(TechnicalRefused, match="pending"):
        finish_inspection(77, inspection.run_id, datetime.now(UTC))
    mark(status="ok")
    with pytest.raises(TechnicalRefused, match="reason"):
        mark("TC002", status="na")
    mark("TC002", status="na", reason="No second fixture at this location")
    assert snapshot(77)["required_pending"] == 0
    done = finish_inspection(77, inspection.run_id, datetime.now(UTC))
    assert done.finished_at is not None
    assert done.technical_snapshot and done.technical_snapshot["checked"] == 2
    with pytest.raises(TechnicalConflict):
        mark(status="pending")


def test_shared_code_requires_separate_acknowledgement_and_changed_evidence_invalidates(
    technical_env: Path,
) -> None:
    finding = add_finding(
        77,
        code="CLN05",
        zone="hot_kitchen",
        level="D1",
        text="Observed surface defect",
        photos=["sample-photo"],
    )
    before = snapshot(77)
    assert [row["status"] for row in before["checks"][:2]] == ["pending", "pending"]
    assert before["checks"][0]["candidate_finding_numbers"] == [finding.n]
    mark(status="issue", finding_numbers=[finding.n])
    assert [row["status"] for row in snapshot(77)["checks"][:2]] == ["issue", "pending"]
    mark("TC002", status="ok")
    with pytest.raises(TechnicalRefused, match="issue"):
        mark(status="ok")
    edit_finding(77, finding.n, text="Observed defect updated")
    assert snapshot(77)["checks"][0]["status"] == "pending"
    mark(status="issue", finding_numbers=[finding.n])
    drop_finding(77, finding.n)
    assert snapshot(77)["checks"][0]["status"] == "pending"


def test_new_finding_does_not_resurrect_old_ok_after_drop(technical_env: Path) -> None:
    mark(status="ok")
    finding = add_finding(
        77,
        code="CLN05",
        zone="hot_kitchen",
        level="D1",
        text="New observation",
        photos=["sample-photo"],
    )
    drop_finding(77, finding.n)
    assert snapshot(77)["checks"][0]["status"] == "pending"


def test_information_requiring_photo_needs_real_d0_evidence(technical_env: Path) -> None:
    with pytest.raises(TechnicalRefused, match="photo"):
        mark("TC003", status="ok")
    finding = add_finding(
        77,
        code="INF09",
        zone="hot_kitchen",
        level="D0",
        text="Oven display: 6 minutes, 260 C",
        photos=["sample-photo"],
    )
    mark("TC003", status="recorded", finding_numbers=[finding.n])
    assert snapshot(77)["checks"][2]["status"] == "recorded"


def test_revision_and_run_identity_reject_stale_confirmations(technical_env: Path) -> None:
    before = snapshot(77)
    mark(status="ok", expected_revision=before["revision"])
    with pytest.raises(TechnicalConflict):
        mark("TC002", status="ok", expected_revision=before["revision"])
    with pytest.raises(TechnicalConflict):
        confirm(77, run_id="other-run", check_id="TC002", zone="hot_kitchen", status="ok")


def test_manifest_is_pinned_and_old_runs_are_not_backfilled(technical_env: Path) -> None:
    (technical_env / "technical_checks.json").unlink()
    assert snapshot(77)["enabled"] is True
    path = state_file(77, check_environment())
    raw = json.loads(path.read_text())
    raw["domain"].pop("technical_enabled")
    path.write_text(json.dumps(raw))
    assert snapshot(77)["enabled"] is False


def test_evidence_without_photo_cannot_close_checkpoint(technical_env: Path) -> None:
    finding = add_finding(
        77,
        code="CLN05",
        zone="hot_kitchen",
        level="D1",
        text="Observation without evidence",
        photos=[],
    )
    with pytest.raises(TechnicalRefused, match="issue"):
        mark(status="issue", finding_numbers=[finding.n])


def test_durable_report_snapshot_cannot_bypass_required_confirmations(technical_env: Path) -> None:
    from src.domain import completion
    from src.domain.revision import revision
    from src.domain.state import read_state

    inspection = get_state(77)
    assert inspection is not None
    with pytest.raises(TechnicalRefused, match="pending"):
        completion.snapshot(77, inspection.run_id, revision(inspection))
    mark(status="ok")
    mark("TC002", status="ok")
    inspection = get_state(77)
    assert inspection is not None
    job = completion.snapshot(77, inspection.run_id, revision(inspection))
    frozen = read_state(77, job)
    assert frozen is not None
    assert frozen.technical_snapshot and frozen.technical_snapshot["checked"] == 2


def test_signed_api_rejects_unsigned_stale_and_submitted_writes(
    technical_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bot_harness import bound_only
    from test_web_walk import ТОКЕН, _приложение, подписать

    from src.domain.handover import HANDED_OVER_KEY, NOTES_FILE_NAME
    from src.web import walk, walk_access
    from src.web.walk_technical import PATH

    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    monkeypatch.setattr(walk_access.bot_links, "standing", bound_only(77, 777))
    client = _приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client()
    inspection = get_state(77)
    assert inspection is not None
    body = {"run_id": inspection.run_id, "check_id": "TC001", "zone": "hot_kitchen", "status": "ok"}
    assert client.post(PATH, json=body).status_code == 401
    headers = {"X-Telegram-Init-Data": подписать(77)}
    assert client.post(PATH, json={**body, "run_id": "old"}, headers=headers).status_code == 409
    response = client.post(PATH, json=body, headers=headers)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["technical"]["checks"][0]["status"] == "ok"
    notes = state_file(77, check_environment()).parent / NOTES_FILE_NAME
    notes.write_text(json.dumps({HANDED_OVER_KEY: 0}))
    assert client.post(PATH, json={**body, "status": "pending"}, headers=headers).status_code == 409
    assert snapshot(77)["checks"][0]["status"] == "ok"


def test_country_limited_checkpoint_is_not_required_outside_its_countries(
    technical_env: Path,
) -> None:
    path = technical_env / "technical_checks.json"
    manifest = json.loads(path.read_text())
    manifest["checks"][0]["countries"] = ["MD", "EE", "ME"]
    path.write_text(json.dumps(manifest))
    inspection = start_inspection(88, unit="Belgrade-1", kind="planned", report_lang="en")
    result = snapshot(88)
    assert result["total"] == 2
    assert result["required_pending"] == 1
    with pytest.raises(TechnicalRefused):
        confirm(88, run_id=inspection.run_id, check_id="TC001", zone="hot_kitchen", status="ok")
