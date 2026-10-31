"""A delayed request belongs to its captured server run, including raw uploads."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import JPEG, Клиент, _нарушение, _совет, клиент  # noqa: F401

from src.domain import get_state, start_inspection
from src.web import walk_write


@pytest.mark.parametrize("op", ["info", "add", "edit", "drop", "attach", "detach"])
def test_old_run_cannot_write_into_replacement(клиент: Клиент, op: str) -> None:  # noqa: F811
    old_run = get_state(АУДИТОР).run_id
    old_ref = клиент.ссылка()
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru")
    current_ref = клиент.ссылка(JPEG)
    assert клиент.запись(**_нарушение(current_ref)).status_code == 200
    before = get_state(АУДИТОР)
    body: dict[str, Any] = {"run_id": old_run}
    if op == "info":
        reply = клиент.сведение(code="INF01", value="old answer", **body)
    elif op == "add":
        reply = клиент.запись(**_совет(text="old words", **body))
    else:
        reply = клиент.запись(op=op, n=1, text="old words", ref=old_ref, **body)
    assert reply.status_code == 409
    assert reply.get_json()["error"] == "run_changed"
    assert get_state(АУДИТОР) == before


def test_stale_raw_upload_is_rejected_before_storage(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_run = get_state(АУДИТОР).run_id
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru")
    before = get_state(АУДИТОР)
    monkeypatch.setattr(walk_write, "save_upload", lambda *a, **k: pytest.fail("stale photo saved"))
    reply = клиент.c.post(
        walk_write.PHOTO_PATH,
        data=JPEG,
        content_type="image/jpeg",
        headers={
            "X-Telegram-Init-Data": клиент.init,
            "X-Walk-Run-Id": old_run,
        },
    )
    assert reply.status_code == 409
    assert reply.get_json()["error"] == "run_changed"
    assert get_state(АУДИТОР) == before


def test_run_is_reread_inside_notes_lock(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_run = get_state(АУДИТОР).run_id
    original = walk_write.while_open

    @contextmanager
    def replace_before_lock_body(who: int):
        with original(who):
            start_inspection(who, unit="replacement", kind="planned", report_lang="ru")
            yield

    monkeypatch.setattr(walk_write, "while_open", replace_before_lock_body)
    reply = клиент.сведение(code="INF01", value="old answer", run_id=old_run)
    assert reply.status_code == 409
    current = get_state(АУДИТОР)
    assert current.unit == "replacement" and current.info == {}


def test_matching_run_and_legacy_without_run_still_write(клиент: Клиент) -> None:  # noqa: F811
    run_id = get_state(АУДИТОР).run_id
    assert клиент.запись(**_совет(text="matching run", run_id=run_id)).status_code == 200
    assert клиент.запись(**_совет(text="legacy client")).status_code == 200
    assert len(get_state(АУДИТОР).findings) == 2
