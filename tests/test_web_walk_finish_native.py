"""Miniapp finishes through the existing domain/bot pipeline; no outbound calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_app import База, _действие, база  # noqa: F401
from test_web_walk_finish import _клиент, _начать


def test_native_review_is_available_without_sending_chat_messages(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.domain.config import check_environment
    from src.domain.engine import state_file
    from src.web import walk_finish

    _начать()
    source = state_file(АУДИТОР, check_environment())
    original = source.read_bytes()
    sends = []
    monkeypatch.setattr(walk_finish, "send_summary", lambda *args: sends.append(args))
    client = _клиент(monkeypatch)
    response = _действие(client, АУДИТОР, op="finish_review")
    assert response.status_code == 200
    review: dict[str, Any] = response.get_json()
    assert review["summary"]["grade"]
    assert review["revision"] and review["run_id"]
    assert review["data"]["info"]
    assert sends == []
    assert source.read_bytes() == original


@pytest.fixture
def report_launch(monkeypatch: pytest.MonkeyPatch):
    from src.db.busy_lock import Hold
    from src.web import walk_finish

    launched = []
    walk_finish._building.clear()
    walk_finish._holds.clear()
    monkeypatch.setattr(walk_finish, "try_hold", lambda *_: Hold(acquired=True))

    class Thread:
        def __init__(self, **kwargs):
            self.args = kwargs

        def start(self):
            launched.append(self.args)

    monkeypatch.setattr(walk_finish.threading, "Thread", Thread)
    yield launched
    for chat in list(walk_finish._building):
        walk_finish._free(chat)


def submit(client, review, **changes):
    return _действие(
        client,
        АУДИТОР,
        op="finish_submit",
        run_id=review["run_id"],
        revision=review["revision"],
        report_lang="en",
        confirmed=True,
        **changes,
    )


def test_native_skip_is_explicit_and_does_not_invent_answers(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from src.domain import get_state

    _начать()
    client = _клиент(monkeypatch)
    review = _действие(client, АУДИТОР, op="finish_review").get_json()
    assert submit(client, review).status_code == 409
    assert report_launch == []
    response = submit(client, review, skip_missing_info=True)
    assert response.status_code == 200 and response.get_json()["status"] == "started"
    assert len(report_launch) == 1
    assert get_state(АУДИТОР).info == {}
    # The language changed during launch; retry still resolves to the same busy build.
    repeated = submit(client, review, skip_missing_info=True)
    assert repeated.status_code == 200 and repeated.get_json()["status"] == "busy"
    assert len(report_launch) == 1


def test_native_rejects_stale_review_and_other_run(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from src.domain import set_info

    _начать()
    client = _клиент(monkeypatch)
    review = _действие(client, АУДИТОР, op="finish_review").get_json()
    set_info(АУДИТОР, "INF01", "Synthetic feedback changed after review")
    assert submit(client, review, skip_missing_info=True).status_code == 409
    review["run_id"] = "different-run"
    assert submit(client, review, skip_missing_info=True).status_code == 409
    assert report_launch == []


def test_native_requires_confirmation_before_build(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    _начать()
    client = _клиент(monkeypatch)
    review = _действие(client, АУДИТОР, op="finish_review").get_json()
    response = _действие(
        client,
        АУДИТОР,
        op="finish_submit",
        run_id=review["run_id"],
        revision=review["revision"],
        skip_missing_info=True,
        report_lang="en",
    )
    assert response.status_code == 400 and report_launch == []


def test_native_finished_retry_uses_durable_completion_without_new_build(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from src.domain.state import finish_inspection
    from src.domain.timing import utc_now

    _начать()
    client = _клиент(monkeypatch)
    review = _действие(client, АУДИТОР, op="finish_review").get_json()
    finished = finish_inspection(АУДИТОР, review["run_id"], utc_now())
    response = submit(client, review, skip_missing_info=True)
    assert response.status_code == 200
    assert response.get_json()["status"] == "completed"
    assert response.get_json()["data"]["timing"]["finished_at"] == finished.finished_at.isoformat()
    assert report_launch == []


def test_native_operations_require_signed_access(
    база: База,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from src.web.walk_auth import APP_PATH

    client = _клиент(monkeypatch)
    for op in ("finish_review", "finish_prepare", "finish_submit", "finish_status"):
        assert client.post(APP_PATH, json={"op": op}).status_code == 401
    assert report_launch == []


def test_prepare_language_precedes_typed_info_and_keeps_free_text(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from test_web_walk_write import Клиент

    from src.domain import get_state, set_info

    _начать()
    set_info(АУДИТОР, "INF01", "Human feedback is kept verbatim")
    set_info(АУДИТОР, "INF07", "31.10.2026")
    client = _клиент(monkeypatch)
    before = _действие(client, АУДИТОР, op="finish_review").get_json()
    prepared = _действие(
        client, АУДИТОР, op="finish_prepare", run_id=before["run_id"], report_lang="en"
    )
    assert prepared.status_code == 200 and prepared.get_json()["status"] == "ready"
    assert get_state(АУДИТОР).report_lang == "en"
    assert get_state(АУДИТОР).info["INF01"].text == "Human feedback is kept verbatim"
    assert get_state(АУДИТОР).info["INF07"].text == "31.10.2026"
    response = Клиент(client).сведение(code="INF03", value="yes", run_id=before["run_id"])
    assert response.status_code == 200
    assert get_state(АУДИТОР).info["INF03"].text == "Yes"
    after = _действие(client, АУДИТОР, op="finish_review").get_json()
    assert after["revision"] != before["revision"]
    assert (
        next(field for field in after["data"]["info"] if field["code"] == "INF03")["value"] == "Yes"
    )
    assert report_launch == []


def test_prepare_never_changes_pending_finished_stale_or_invalid_language(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from src.domain import get_state
    from src.domain.state import finish_inspection
    from src.domain.timing import utc_now
    from src.web import walk_finish

    _начать()
    client = _клиент(monkeypatch)
    run = get_state(АУДИТОР).run_id

    def prepare(**changes):
        body = {"run_id": run, "report_lang": "en"} | changes
        return _действие(client, АУДИТОР, op="finish_prepare", **body)

    assert prepare(run_id="other-run").status_code == 409
    assert prepare(report_lang="not-offered").status_code == 409
    walk_finish._building.add(АУДИТОР)
    assert prepare().get_json()["status"] == "busy"
    walk_finish._building.clear()
    assert get_state(АУДИТОР).report_lang == "ru"
    finished = finish_inspection(АУДИТОР, run, utc_now())
    assert prepare().get_json()["status"] == "completed"
    assert get_state(АУДИТОР).report_lang == "ru"
    assert get_state(АУДИТОР).finished_at == finished.finished_at


def test_review_warns_only_for_authoritatively_skipped_existing_feedback(
    база: База,  # noqa: F811
    domain_env: Path,
    data_copy: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from test_engine_letter_feedback import _роли

    from src.domain import get_state, set_info
    from src.domain.config import check_environment
    from src.domain.engine import state_file

    _роли(data_copy, {"INF01": "strengths", "INF06": "growth"})
    monkeypatch.setenv("AUDIT_DATA_DIR", str(data_copy))
    _начать()
    client = _клиент(monkeypatch)
    run = get_state(АУДИТОР).run_id
    assert (
        _действие(client, АУДИТОР, op="finish_prepare", run_id=run, report_lang="en").status_code
        == 200
    )
    set_info(АУДИТОР, "INF06", "", photos=["AgACsynthetic-photo-only"])
    empty = _действие(client, АУДИТОР, op="finish_review").get_json()
    assert empty["summary"]["feedback_skipped"] == []
    set_info(АУДИТОР, "INF01", "Human text remains unchanged")
    path = state_file(АУДИТОР, check_environment())
    source = path.read_bytes()
    review = _действие(client, АУДИТОР, op="finish_review").get_json()
    assert review["summary"]["feedback_skipped"] == ["strengths"]
    assert review["summary"]["feedback_lang"] == "ru"
    assert path.read_bytes() == source and report_launch == []


def test_prepare_refuses_sealed_inspection_without_changing_its_language(
    база: База,  # noqa: F811
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    report_launch,
):
    from src.bot.sidecar import mark_handed_over
    from src.domain import get_state

    _начать()
    run = get_state(АУДИТОР).run_id
    mark_handed_over(АУДИТОР, 0)
    client = _клиент(monkeypatch)
    response = _действие(client, АУДИТОР, op="finish_prepare", run_id=run, report_lang="en")
    assert response.status_code == 409 and get_state(АУДИТОР).report_lang == "ru"
    assert report_launch == []
