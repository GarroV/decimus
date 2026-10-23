"""Пределы сервера названы явно, а медленный путь не занимает все потоки (F-121).

Ядро здесь — отказ без ожидания: проба на порчу — убрать `SlowGate` из
`walk_proxy.install`, и третий запрос повиснет вместе с двумя, а не получит
503 за миллисекунды.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from flask import Flask

from src.web import walk_proxy
from src.web.errors import WebConfigError
from src.web.server_limits import (
    BODY_OVERHEAD_BYTES,
    DEFAULT_CHANNEL_TIMEOUT_SEC,
    DEFAULT_CONNECTION_LIMIT,
    DEFAULT_THREADS,
    SlowGate,
    default_max_body_bytes,
    server_options,
)
from src.web.walk_auth import PAGE_PATH

MB = 1024 * 1024


def test_умолчания_названы_а_не_унаследованы() -> None:
    options = server_options({})

    assert options["threads"] == DEFAULT_THREADS == 8
    assert options["connection_limit"] == DEFAULT_CONNECTION_LIMIT
    assert options["channel_timeout"] == DEFAULT_CHANNEL_TIMEOUT_SEC < 120
    # Пачка кадров одной записи (10 × 10 МиБ) проходит, гигабайт — нет.
    assert 100 * MB <= options["max_request_body_size"] < 1024 * MB


def test_предел_тела_поднимается_вслед_за_вложением_предписания() -> None:
    assert default_max_body_bytes({"ATTACHMENT_MAX_MB": "300"}) == 300 * MB + BODY_OVERHEAD_BYTES


def test_предел_тела_можно_назвать_руками() -> None:
    assert server_options({"WEB_MAX_BODY_MB": "40"})["max_request_body_size"] == 40 * MB


@pytest.mark.parametrize(
    ("name", "value"),
    [("WEB_THREADS", "0"), ("WEB_THREADS", "много"), ("WEB_MAX_BODY_MB", "-1")],
)
def test_мусор_в_пределах_отказ_на_старте(name: str, value: str) -> None:
    with pytest.raises(WebConfigError, match=name):
        server_options({name: value})


def test_ворота_пускают_названное_число_и_отказывают_без_ожидания() -> None:
    gate = SlowGate(2)

    assert gate.try_enter() and gate.try_enter()
    started = time.monotonic()
    assert not gate.try_enter()
    assert time.monotonic() - started < 0.1
    gate.leave()
    assert gate.try_enter()


@pytest.fixture
def медленный_обход() -> Iterator[tuple[str, threading.Event, list[str]]]:
    """Сервис, не отвечающий, пока не дадут отмашку, — как подбор пункта моделью."""
    release = threading.Event()
    arrived: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            arrived.append(self.path)
            release.wait(timeout=30)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: object) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", release, arrived
    finally:
        release.set()
        httpd.shutdown()
        httpd.server_close()


def test_занятый_проход_к_обходу_отказывает_сразу_а_не_виснет(
    медленный_обход: tuple[str, threading.Event, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream, release, arrived = медленный_обход
    monkeypatch.setenv("WEB_WALK_PROXY_MAX", "2")
    app = Flask(__name__)
    walk_proxy.install(app, upstream=upstream, ui_lang="ru")
    busy = [
        threading.Thread(target=lambda: app.test_client().get(PAGE_PATH), daemon=True)
        for _ in range(2)
    ]
    for thread in busy:
        thread.start()
    deadline = time.monotonic() + 5
    while len(arrived) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(arrived) == 2, "два запроса должны были дойти до сервиса обхода и повиснуть"

    started = time.monotonic()
    answer = app.test_client().get(PAGE_PATH)
    elapsed = time.monotonic() - started

    assert answer.status_code == 503
    assert answer.headers["Retry-After"] == str(walk_proxy.OVERLOAD_RETRY_AFTER_SEC)
    assert elapsed < 1.0, "отказ должен быть быстрым, а не ожиданием слота"
    assert len(arrived) == 2, "третий запрос не должен был дойти до сервиса обхода"

    release.set()
    for thread in busy:
        thread.join(timeout=5)
    assert app.test_client().get(PAGE_PATH).status_code == 200, "слоты не освободились"
