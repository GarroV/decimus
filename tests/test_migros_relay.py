"""Migros через домашний сервер (D434): ретранслятор, сборщик через него, уведомление.

Сбор ненадёжен по природе (домашний сервер засыпает), поэтому проверяется вся
цепочка до сообщения: что ретранслятор не стал открытым прокси, что сбой
доходит до сборщика понятной причиной без адреса и что уведомление уходит
только заданному адресату."""

from __future__ import annotations

import threading
import urllib.error
from collections.abc import Iterator
from datetime import date
from http.server import HTTPServer
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


@pytest.mark.parametrize(("сырое", "id"), [("", None), (" ", None), ("abc", None), ("123", 123)])
def test_адресат_из_переменной(сырое: str, id: int | None) -> None:
    assert alert.chat_id(сырое) == id


class _Бот:
    def __init__(self, падать: bool = False) -> None:
        self.отправлено: list[tuple[int, str]] = []
        self.падать = падать

    async def send_message(self, chat_id: int, text: str) -> None:
        if self.падать:
            raise RuntimeError("telegram down")
        self.отправлено.append((chat_id, text))


@pytest.mark.asyncio
async def test_без_адресата_никому_не_пишет(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(alert.CHAT_VAR, raising=False)
    бот = _Бот()
    assert await agg_loader.notify(бот, [СБОЙ]) is False  # type: ignore[arg-type]
    assert бот.отправлено == []


@pytest.mark.asyncio
async def test_сбой_уходит_одному_адресату(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(alert.CHAT_VAR, "777")
    бот = _Бот()
    assert await agg_loader.notify(бот, [ОК, СБОЙ]) is True  # type: ignore[arg-type]
    assert [чат for чат, _ in бот.отправлено] == [777]
    assert "Migros Yemek" in бот.отправлено[0][1]


@pytest.mark.asyncio
async def test_без_сбоя_молчит(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(alert.CHAT_VAR, "777")
    бот = _Бот()
    assert await agg_loader.notify(бот, [ОК]) is False  # type: ignore[arg-type]
    assert бот.отправлено == []


@pytest.mark.asyncio
async def test_сбой_отправки_не_роняет_сбор(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(alert.CHAT_VAR, "777")
    assert await agg_loader.notify(_Бот(падать=True), [СБОЙ]) is False  # type: ignore[arg-type]


def test_заявка_не_уведомляет(monkeypatch: pytest.MonkeyPatch) -> None:
    """Итоги для уведомления — только суточного сбора; заявку видит нажавший."""
    monkeypatch.setattr(agg_loader.queue, "fulfil", lambda **_: True)
    monkeypatch.setattr(agg_loader.collect, "run_all", lambda *_: (СБОЙ,))
    assert agg_loader._tick(scheduled=True) == ()


def test_суточный_сбор_отдаёт_итоги(monkeypatch: pytest.MonkeyPatch) -> None:
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
