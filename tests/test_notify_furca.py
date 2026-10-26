"""Отправка в канал FURCA (D641) против подменного HTTP-сервера: заголовок, тело, отказы."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from src.notify import furca


class _Channel(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, object]]] = []
    status: ClassVar[int] = 200
    delay: ClassVar[float] = 0.0

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).seen.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "type": self.headers.get("Content-Type"),
                "body": json.loads(body),
            }
        )
        time.sleep(type(self).delay)
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def channel() -> Iterator[tuple[str, type[_Channel]]]:
    _Channel.seen, _Channel.status, _Channel.delay = [], 200, 0.0
    server = HTTPServer(("127.0.0.1", 0), _Channel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _Channel
    server.shutdown()
    server.server_close()


def _target(base: str) -> tuple[str, str]:
    found = furca.channel({"FURCA_NOTIFY_URL": base, "FURCA_SECRET": "channel-key"})
    assert found is not None
    return found


def test_отправка_кладёт_ключ_в_заголовок_а_проект_вид_и_текст_в_тело(channel) -> None:
    base, handler = channel
    furca.send(_target(base), "🔴 Decimus · проверка", "alert")
    furca.send(_target(base), "🟢 Decimus · снова", furca.DONE)
    first, second = handler.seen
    assert first["path"] == "/notify"
    assert first["auth"] == "Bearer channel-key"
    assert first["type"] == "application/json"
    assert first["body"] == {"project": "decimus", "kind": "alert", "text": "🔴 Decimus · проверка"}
    assert second["body"]["kind"] == "done"  # type: ignore[index]


def test_вид_по_умолчанию_alert(channel) -> None:
    base, handler = channel
    furca.send(_target(base), "текст")
    assert handler.seen[0]["body"]["kind"] == "alert"  # type: ignore[index]


@pytest.mark.parametrize("status", [400, 401, 500])
def test_отказ_канала_это_исключение_с_кодом(channel, status: int) -> None:
    base, handler = channel
    handler.status = status
    with pytest.raises(urllib.error.HTTPError) as caught:
        furca.send(_target(base), "текст")
    assert caught.value.code == status


def test_таймаут_это_исключение_а_не_зависание(channel, monkeypatch: pytest.MonkeyPatch) -> None:
    base, handler = channel
    handler.delay = 1.0
    monkeypatch.setattr(furca, "TIMEOUT_SEC", 0.2)
    started = time.monotonic()
    with pytest.raises((TimeoutError, urllib.error.URLError)):
        furca.send(_target(base), "текст")
    assert time.monotonic() - started < 0.9


def test_http_на_внешний_адрес_канал_выключает() -> None:
    env = {"FURCA_NOTIFY_URL": "http://channel.example.com", "FURCA_SECRET": "s"}
    assert furca.channel(env) is None
