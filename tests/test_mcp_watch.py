"""Сторож доступности снаружи: зелёный только на здоровой двери (#243).

Проверяется порчей, а не только зелёным светом: сторож, который не умеет
краснеть, хуже отсутствующего — он создаёт уверенность. Поэтому каждый тест
здесь описывает КОНКРЕТНЫЙ способ сломаться, наблюдавшийся на живом продукте:
502 от туннеля, дверь без замка, пропавший установщик, мёртвый адрес.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tools.mcp_watch import WatchError, check


@contextlib.contextmanager
def _поднять(ответы: dict[str, int]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            код = ответы.get(self.path.split("?")[0], 404)
            self.send_response(код)
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_GET = _answer
        do_POST = _answer

        def log_message(self, *args: object) -> None:  # тишина в выводе тестов
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


@pytest.fixture
def здоровый() -> Iterator[str]:
    """Дверь заперта, установщик отдаётся — то, как выглядит рабочий продукт."""
    with _поднять({"/": 401, "/setup": 200}) as адрес:
        yield адрес


def test_здоровый_продукт_сторож_пропускает(здоровый: str) -> None:
    отчёт = check(здоровый)

    assert any("дверь заперта" in строка for строка in отчёт)
    assert any("установщик" in строка for строка in отчёт)


def test_502_от_туннеля_краснеет() -> None:
    """Ровно то, что было 15.09.2026: контейнеры здоровы, снаружи 502."""
    with _поднять({"/": 502, "/setup": 502}) as сервер, pytest.raises(WatchError, match="502"):
        check(сервер)


def test_дверь_без_замка_краснеет() -> None:
    """200 без токена — это не «работает», а «отдаёт историю проверок кому угодно».

    Сторож обязан считать это отказом: посредник, отвечающий 200 на что
    угодно, выглядит здоровее живого сервера.
    """
    with (
        _поднять({"/": 200, "/setup": 200}) as сервер,
        pytest.raises(WatchError, match="дверь отвечает 200"),
    ):
        check(сервер)


def test_пропавший_установщик_краснеет() -> None:
    """Дверь цела, а подключиться никто не может — тоже отказ."""
    with (
        _поднять({"/": 401, "/setup": 404}) as сервер,
        pytest.raises(WatchError, match="установщик отвечает 404"),
    ):
        check(сервер)


def test_мёртвый_адрес_краснеет() -> None:
    """Уснувшая площадка: соединение не устанавливается вовсе."""
    with pytest.raises(WatchError, match="не ответил"):
        check("http://127.0.0.1:9/")
