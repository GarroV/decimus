"""Migros через домашний сервер (D434): ретранслятор, сборщик через него, уведомление.

Сбор ненадёжен по природе (домашний сервер засыпает), поэтому проверяется вся
цепочка до сообщения: что ретранслятор не стал открытым прокси, что сбой
доходит до сборщика понятной причиной без адреса и что уведомление уходит
только заданному адресату."""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from src.bot import agg_loader
from src.db.agg_store import PointRow
from src.ratings.aggregators import alert, base, migros, migros_relay
from src.ratings.aggregators.base import AggregatorError
from src.ratings.aggregators.collect import Outcome

ТОЧКА = PointRow(
    "migros_yemek", "dodo-pizza-buca-vali-rahmi-bey-mah-st-1", "TR", None, None,
    None, None, "0" * 32, "Izmir-3", None, {},
)  # fmt: skip
КАРТОЧКА = (
    b'{"storeDTO":{"id":1,"title":"Dodo Pizza, Buca (Vali Rahmi Bey Mah.)",'
    b'"rating":{"score":"4,7","commentCount":612},"cityId":35}}'
)


# --- ретранслятор не открытый прокси ---


def test_путь_карточки_ведёт_только_на_migros() -> None:
    assert migros_relay.target("/stores/dodo-pizza-buca-st-1") == (
        "https://www.migros.com.tr/rest/food-bff/api/stores/dodo-pizza-buca-st-1"
    )


@pytest.mark.parametrize(
    "путь",
    [
        "/stores/../admin",
        "/stores/a/b",
        "/stores/a?x=1",
        "/stores/A",
        "/stores/",
        "/stores/-a",
        "/stores/a%2fb",
        "//evil.example/stores/a",
        "/stores/a@evil.example",
        "/other",
        "/stores/" + "a" * 161,
    ],
)
def test_прочие_пути_отказ(путь: str) -> None:
    assert migros_relay.target(путь) is None


@pytest.fixture
def ретранслятор(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[str, list[str], dict[str, Any]]]:
    """Настоящий HTTP-сервер ретранслятора на локальном порту; Migros подменён."""
    зовы: list[str] = []
    ответ: dict[str, Any] = {"status": 200, "body": КАРТОЧКА, "raise": None}

    def migros_ответ(url: str) -> tuple[int, bytes]:
        зовы.append(url)
        if ответ["raise"]:
            raise ответ["raise"]
        return ответ["status"], ответ["body"]

    monkeypatch.setattr(migros_relay, "fetch", migros_ответ)
    сервер = HTTPServer(("127.0.0.1", 0), migros_relay.Handler)
    нить = threading.Thread(target=сервер.serve_forever, daemon=True)
    нить.start()
    try:
        yield f"http://127.0.0.1:{сервер.server_port}", зовы, ответ
    finally:
        сервер.shutdown()
        сервер.server_close()


def _сборщик(monkeypatch: pytest.MonkeyPatch, адрес: str) -> base.Http:
    monkeypatch.setenv(migros.RELAY_VAR, адрес + "/")
    monkeypatch.setattr(base, "BACKOFF_SEC", 0)
    return base.Http(0)


def test_сборщик_через_ретранслятор_получает_оценку(
    monkeypatch: pytest.MonkeyPatch, ретранслятор: tuple[str, list[str], dict[str, Any]]
) -> None:
    адрес, зовы, _ = ретранслятор
    найдено = migros.refresh(_сборщик(monkeypatch, адрес), ТОЧКА)
    assert (найдено.score, найдено.votes) == (4.7, 612)
    assert зовы == [migros_relay.UPSTREAM.format(slug=ТОЧКА.point_key)]


def test_403_migros_доходит_причиной_без_адреса(
    monkeypatch: pytest.MonkeyPatch, ретранслятор: tuple[str, list[str], dict[str, Any]]
) -> None:
    адрес, _, ответ = ретранслятор
    ответ.update(status=403, body=b"<html>blocked</html>")
    with pytest.raises(AggregatorError) as отказ:
        migros.refresh(_сборщик(monkeypatch, адрес), ТОЧКА)
    assert str(отказ.value) == "Migros ответил HTTP 403 (через домашний сервер)"
    assert "127.0.0.1" not in str(отказ.value)


def test_migros_недоступен_ретранслятор_502(
    monkeypatch: pytest.MonkeyPatch, ретранслятор: tuple[str, list[str], dict[str, Any]]
) -> None:
    адрес, _, ответ = ретранслятор
    ответ["raise"] = urllib.error.URLError("dns")
    with pytest.raises(AggregatorError, match="Migros ответил HTTP 502"):
        migros.refresh(_сборщик(monkeypatch, адрес), ТОЧКА)


def test_чужой_путь_у_ретранслятора_404(
    ретранслятор: tuple[str, list[str], dict[str, Any]],
) -> None:
    адрес, зовы, _ = ретранслятор
    with pytest.raises(urllib.error.HTTPError) as отказ:
        urllib.request.urlopen(f"{адрес}/stores/../x")  # noqa: S310
    assert отказ.value.code == 404
    assert зовы == []


def test_домашний_сервер_спит(monkeypatch: pytest.MonkeyPatch) -> None:
    # Порт, на котором никто не слушает: так выглядит уснувший MUSPELHEIM.
    сервер = HTTPServer(("127.0.0.1", 0), migros_relay.Handler)
    порт = сервер.server_port
    сервер.server_close()
    with pytest.raises(AggregatorError, match=r"^домашний сервер не отвечает"):
        migros.refresh(_сборщик(monkeypatch, f"http://127.0.0.1:{порт}"), ТОЧКА)


def test_ретранслятор_не_задан_своя_причина(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(migros.RELAY_VAR, raising=False)
    with pytest.raises(AggregatorError, match="не задан MIGROS_RELAY_URL"):
        migros.refresh(base.Http(0), ТОЧКА)


# --- уведомление ---

СБОЙ = Outcome("migros_yemek", False, 0, 0, "не ответил ни на один из 28 запросов")
ОК = Outcome("wolt", True, 45, 45, None)


def test_всё_собралось_писать_не_о_чем() -> None:
    assert alert.message([ОК]) is None


def test_сбой_назван_и_подсказка_про_домашний_сервер() -> None:
    текст = alert.message([ОК, СБОЙ])
    assert текст is not None
    assert "• Migros Yemek: не ответил ни на один из 28 запросов" in текст
    assert "Wolt" not in текст
    assert "домашний сервер" in текст


def test_длинная_причина_обрезана() -> None:
    текст = alert.message([Outcome("wolt", False, 0, 0, "x" * 500)])
    assert текст is not None and "x" * 200 not in текст and "…" in текст


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"FURCA_NOTIFY_URL": "http://ch:8090"},
        {"FURCA_SECRET": "s"},
        {"FURCA_NOTIFY_URL": "ch:8090", "FURCA_SECRET": "s"},
        {"FURCA_NOTIFY_URL": " ", "FURCA_SECRET": "s"},
    ],
)
def test_канал_не_задан_уведомление_выключено(env: dict[str, str]) -> None:
    assert alert.channel(env) is None


def test_канал_задан() -> None:
    env = {"FURCA_NOTIFY_URL": "http://ch:8090/", "FURCA_SECRET": "s"}
    assert alert.channel(env) == ("http://ch:8090/notify", "s")


@pytest.fixture
def канал(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Настоящий HTTP-приёмник вместо канала FURCA; адрес и ключ — в окружении."""
    принято: list[dict[str, Any]] = []

    class Приёмник(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            тело = self.rfile.read(int(self.headers["Content-Length"]))
            принято.append(
                {"path": self.path, "auth": self.headers["Authorization"], **json.loads(тело)}
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            pass

    сервер = HTTPServer(("127.0.0.1", 0), Приёмник)
    threading.Thread(target=сервер.serve_forever, daemon=True).start()
    monkeypatch.setenv(alert.URL_VAR, f"http://127.0.0.1:{сервер.server_port}")
    monkeypatch.setenv(alert.SECRET_VAR, "channel-key")
    try:
        yield принято
    finally:
        сервер.shutdown()
        сервер.server_close()


@pytest.mark.asyncio
async def test_без_канала_никуда_не_уходит(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(alert.URL_VAR, raising=False)
    monkeypatch.delenv(alert.SECRET_VAR, raising=False)
    отправки: list[object] = []
    monkeypatch.setattr(alert, "send", lambda *a: отправки.append(a))
    assert await agg_loader.notify([СБОЙ]) is False
    assert отправки == []


@pytest.mark.asyncio
async def test_сбой_уходит_тревогой_в_канал(канал: list[dict[str, Any]]) -> None:
    assert await agg_loader.notify([ОК, СБОЙ]) is True
    assert len(канал) == 1
    тревога = канал[0]
    assert (тревога["path"], тревога["auth"]) == ("/notify", "Bearer channel-key")
    assert (тревога["project"], тревога["kind"]) == ("decimus", "alert")
    assert "Migros Yemek" in тревога["text"] and "Wolt" not in тревога["text"]


@pytest.mark.asyncio
async def test_без_сбоя_молчит(канал: list[dict[str, Any]]) -> None:
    assert await agg_loader.notify([ОК]) is False
    assert канал == []


@pytest.mark.asyncio
async def test_канал_лежит_сбор_не_падает(monkeypatch: pytest.MonkeyPatch) -> None:
    сервер = HTTPServer(("127.0.0.1", 0), migros_relay.Handler)
    порт = сервер.server_port
    сервер.server_close()
    monkeypatch.setenv(alert.URL_VAR, f"http://127.0.0.1:{порт}")
    monkeypatch.setenv(alert.SECRET_VAR, "s")
    assert await agg_loader.notify([СБОЙ]) is False


def test_заявка_не_уведомляет(monkeypatch: pytest.MonkeyPatch) -> None:
    """Итоги для уведомления — только суточного сбора; заявку видит нажавший."""
    monkeypatch.setattr(agg_loader.agg_store, "collector_lock", lambda: nullcontext(True))
    monkeypatch.setattr(agg_loader.queue, "fulfil", lambda **_: True)
    monkeypatch.setattr(agg_loader.collect, "run_all", lambda *_: (СБОЙ,))
    assert agg_loader._tick(scheduled=True) == ()


def test_суточный_сбор_отдаёт_итоги(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agg_loader.agg_store, "collector_lock", lambda: nullcontext(True))
    monkeypatch.setattr(agg_loader.queue, "fulfil", lambda **_: False)
    monkeypatch.setattr(agg_loader, "_due", lambda: True)
    monkeypatch.setattr(agg_loader.collect, "run_all", lambda *_: (СБОЙ,))
    assert agg_loader._tick(scheduled=True) == (СБОЙ,)
    assert date.today()  # сбор зовётся с сегодняшней датой — сам вызов подменён


@pytest.mark.parametrize(
    "адрес",
    [
        "http://example.com/x",
        "http://100.64.1.2.evil.example/x",
        "http://8.8.8.8/x",
        "ftp://100.64.1.2/x",
    ],
)
def test_http_только_в_сеть_tailscale(адрес: str) -> None:
    with pytest.raises(AggregatorError, match="Не https-адрес"):
        base._https(адрес)


def test_http_в_сеть_tailscale_можно() -> None:
    assert base._https("http://100.64.1.2:9021/stores/a") == "http://100.64.1.2:9021/stores/a"


def test_обрыв_соединения_тоже_домашний_сервер(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tailscale принимает соединение, а ретранслятор лежит: соединение рвётся."""
    приёмник = socket.socket()
    приёмник.bind(("127.0.0.1", 0))
    приёмник.listen()

    def рвать() -> None:
        for _ in range(base.RETRIES):
            связь, _ = приёмник.accept()
            связь.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00"
            )
            связь.close()

    threading.Thread(target=рвать, daemon=True).start()
    адрес = f"http://127.0.0.1:{приёмник.getsockname()[1]}"
    try:
        with pytest.raises(AggregatorError, match=r"^домашний сервер не отвечает"):
            migros.refresh(_сборщик(monkeypatch, адрес), ТОЧКА)
    finally:
        приёмник.close()
