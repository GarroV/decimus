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
    from src.web import walk_finish

    _начать()
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
    for op in ("finish_review", "finish_submit", "finish_status"):
        assert client.post(APP_PATH, json={"op": op}).status_code == 401
    assert report_launch == []
