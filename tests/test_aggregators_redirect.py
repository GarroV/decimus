"""Редирект агрегатора не уводит запрос туда, куда начальный адрес не пустили (F-136).

Чистый Python: поднимается сервер на петле, который отвечает 302 на заданный адрес.
Наружу ничего не уходит — недопустимый ход отвергается до соединения.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src.ratings.aggregators import base
from src.ratings.aggregators.base import AggregatorError, Http


def _serve(handler: type[BaseHTTPRequestHandler]) -> Generator[str]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _redirecting(target: str) -> Generator[str]:
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            pass

    yield from _serve(Redirect)


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("http://169.254.169.254/latest/meta-data/", "не-https адрес"),
        ("https://169.254.169.254/latest/meta-data/", "закрытый адрес"),
        ("https://10.0.0.5/admin", "закрытый адрес"),
        ("https://192.168.1.1/", "закрытый адрес"),
        ("https://127.0.0.1/", "закрытый адрес"),
        ("https://100.64.1.2/", "закрытый адрес"),
        ("http://127.0.0.1/", "не-https адрес"),
        ("http://100.64.1.2/", "не-https адрес"),
        ("http://example.com/", "не-https адрес"),
        ("file:///etc/passwd", "HTTP 302"),  # схему режет сам urllib,
    ],
)
def test_redirect_to_forbidden_target_is_rejected(target: str, reason: str) -> None:
    gen = _redirecting(target)
    origin = next(gen)
    try:
        with pytest.raises(AggregatorError, match=reason):
            Http(gap_sec=0).get(f"{origin}/start")
    finally:
        gen.close()


def test_public_https_hop_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 0))])
    assert base._check_hop("https://example.com/next") == "https://example.com/next"


def test_hop_resolving_to_internal_address_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        base.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 0))]
    )
    with pytest.raises(AggregatorError, match="закрытый адрес"):
        base._check_hop("https://innocent.example/")
