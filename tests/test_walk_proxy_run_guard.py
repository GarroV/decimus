"""The admin proxy must preserve the raw-photo run guard end to end, without a server."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from flask import Flask
from test_web_walk import АУДИТОР
from test_web_walk_write import JPEG, Клиент, клиент  # noqa: F401

from src.domain import get_state, start_inspection
from src.web import walk_proxy, walk_write


def test_proxy_keeps_run_header_and_service_rejects_stale_photo(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous_run = get_state(АУДИТОР).run_id
    start_inspection(АУДИТОР, unit="replacement", kind="planned", report_lang="ru")
    current = get_state(АУДИТОР)
    sent = []

    @contextmanager
    def service(outgoing, **_kwargs):
        headers = dict(outgoing.header_items())
        sent.append({name.lower(): value for name, value in headers.items()})
        reply = клиент.c.post(urlsplit(outgoing.full_url).path, data=outgoing.data, headers=headers)
        yield SimpleNamespace(status=reply.status_code, read=reply.get_data, headers=reply.headers)

    monkeypatch.setattr(walk_proxy._OPENER, "open", service)
    proxy = Flask(__name__)
    walk_proxy.install(proxy, upstream="http://walk.invalid", ui_lang="ru")
    client = proxy.test_client()
    reply = client.post(
        walk_write.PHOTO_PATH,
        data=JPEG,
        content_type="image/jpeg",
        headers={
            "X-Telegram-Init-Data": клиент.init,
            "X-Walk-Run-Id": previous_run,
            "Authorization": "not-forwarded",
        },
    )
    assert reply.status_code == 409
    assert reply.get_json()["error"] == "run_changed"
    assert sent[0]["x-walk-run-id"] == previous_run
    assert "authorization" not in sent[0]
    assert get_state(АУДИТОР) == current
    # The same path remains compatible with current and legacy clients.
    for run_id in (current.run_id, None):
        headers = {"X-Telegram-Init-Data": клиент.init}
        if run_id is not None:
            headers["X-Walk-Run-Id"] = run_id
        assert (
            client.post(
                walk_write.PHOTO_PATH, data=JPEG, content_type="image/jpeg", headers=headers
            ).status_code
            == 201
        )
