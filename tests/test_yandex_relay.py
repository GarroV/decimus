"""Яндекс Еда через домашний сервер (D661): ретранслятор не стал открытым прокси,
сборщик через него получает оценку, сбой доходит понятной причиной без адреса,
а без адреса сбор остаётся на паузе."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import HTTPServer
from typing import Any

import pytest

from src.ratings.aggregators import base, collect, migros, migros_relay, yandex_eda
from src.ratings.aggregators.base import AggregatorError

ВЫДАЧА = {
    "blocks": [
        {
            "payload": [
                {
                    "slug": "dodo_kwls7",
                    "title": "Додо Пицца",
                    "brand": {"slug": "dodo_picca"},
                    "available": True,
                }
            ]
        }
    ]
}
КАРТОЧКА = {
    "payload": {
        "foundPlace": {
            "place": {
                "name": "Додо Пицца",
                "rating": 4.6,
                "ratingCount": "870",
                "brand": {"slug": "dodo_picca"},
                "address": {"location": {"latitude": 53.9, "longitude": 27.5}, "short": "Минск"},
            }
        }
    }
}
ТЕЛО = {"text": "Додо", "location": {"latitude": 53.9, "longitude": 27.5667}}


def _тело(данные: object) -> bytes:
    return json.dumps(данные).encode()


# --- ретранслятор не открытый прокси ---


def test_поиск_пересобирается_из_проверенных_полей() -> None:
    assert json.loads(migros_relay.yandex_search_body(_тело(ТЕЛО)) or b"") == ТЕЛО


@pytest.mark.parametrize(
    "тело",
    [
        b"not json",
        b"[]",
        _тело({"text": "Додо"}),
        _тело({**ТЕЛО, "url": "http://evil.example"}),
        _тело({"text": 5, "location": ТЕЛО["location"]}),
        _тело({"text": "", "location": ТЕЛО["location"]}),
        _тело({"text": "я" * 65, "location": ТЕЛО["location"]}),
        _тело({"text": "Додо", "location": {"latitude": 1, "longitude": 2, "x": 3}}),
        _тело({"text": "Додо", "location": {"latitude": "53.9", "longitude": 27.5}}),
        _тело({"text": "Додо", "location": {"latitude": True, "longitude": 27.5}}),
        _тело({"text": "Додо", "location": {"latitude": 91, "longitude": 27.5}}),
        _тело({"text": "Додо", "location": {"latitude": 53.9, "longitude": 181}}),
        _тело({"text": "Додо", "location": "Минск"}),
        _тело({"text": "я" * 2000, "location": ТЕЛО["location"]}),
    ],
)
def test_кривое_тело_поиска_отказ(тело: bytes) -> None:
    assert migros_relay.yandex_search_body(тело) is None


def test_путь_карточки_ведёт_только_на_яндекс() -> None:
    assert migros_relay.yandex_card_target(
        "/yandex/catalog/dodo_kwls7?latitude=53.9&longitude=27.5667"
    ) == ("https://eda.yandex.by/api/v2/catalog/dodo_kwls7?latitude=53.9&longitude=27.5667")


@pytest.mark.parametrize(
    "путь",
    [
        "/yandex/catalog/../admin?latitude=1&longitude=2",
        "/yandex/catalog/a/b?latitude=1&longitude=2",
        "/yandex/catalog/a",
        "/yandex/catalog/a?latitude=1",
        "/yandex/catalog/a?latitude=1&longitude=2&x=3",
        "/yandex/catalog/a?latitude=x&longitude=2",
        "/yandex/catalog/a?latitude=1&longitude=2%26x",
        "/yandex/catalog/a@evil.example?latitude=1&longitude=2",
        "/yandex/catalog/_a?latitude=1&longitude=2",
        "//evil.example/yandex/catalog/a?latitude=1&longitude=2",
        "/yandex/other?latitude=1&longitude=2",
    ],
)
def test_прочие_пути_карточки_отказ(путь: str) -> None:
    assert migros_relay.yandex_card_target(путь) is None


def test_пауза_у_ретранслятора_своя_для_яндекса() -> None:
    assert migros_relay.YANDEX_GAP_SEC == yandex_eda.GAP_SEC
    assert migros_relay._gaps["yandex"] > migros_relay._gaps["migros"]


@pytest.fixture
def ретранслятор(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[str, list[tuple[str, bytes | None]], dict[str, Any]]]:
    """Настоящий HTTP-сервер ретранслятора; Яндекс подменён."""
    зовы: list[tuple[str, bytes | None]] = []
    ответ: dict[str, Any] = {"status": 200, "raise": None, "search": ВЫДАЧА, "card": КАРТОЧКА}

    def яндекс(url: str, body: bytes | None = None) -> tuple[int, bytes]:
        зовы.append((url, body))
        if ответ["raise"]:
            raise ответ["raise"]
        данные = ответ["search"] if url == migros_relay.YANDEX_SEARCH else ответ["card"]
        return ответ["status"], _тело(данные)

    monkeypatch.setattr(migros_relay, "fetch", яндекс)
    сервер = HTTPServer(("127.0.0.1", 0), migros_relay.Handler)
    нить = threading.Thread(target=сервер.serve_forever, daemon=True)
    нить.start()
    try:
        yield f"http://127.0.0.1:{сервер.server_port}", зовы, ответ
    finally:
        сервер.shutdown()
        сервер.server_close()


def _http(monkeypatch: pytest.MonkeyPatch, адрес: str) -> base.Http:
    monkeypatch.setenv(migros.RELAY_VAR, адрес + "/")
    monkeypatch.setattr(base, "BACKOFF_SEC", 0)
    return base.Http(0)


def _post(адрес: str, путь: str, тело: bytes) -> int:
    запрос = urllib.request.Request(адрес + путь, data=тело, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(запрос) as ответ:  # noqa: S310
            return int(ответ.status)
    except urllib.error.HTTPError as отказ:
        return отказ.code


def test_ретранслятор_отдаёт_поиск_и_карточку(
    monkeypatch: pytest.MonkeyPatch, ретранслятор: tuple[str, list[Any], dict[str, Any]]
) -> None:
    адрес, зовы, _ = ретранслятор
    найдено = yandex_eda.search(_http(monkeypatch, адрес), 53.9, 27.5667, "BY", {})
    assert [(p.point_key, p.score, p.votes, p.is_open) for p in найдено] == [
        ("dodo_kwls7", 4.6, 870, True)
    ]
    assert _адреса(зовы) == [
        migros_relay.YANDEX_SEARCH,
        "https://eda.yandex.by/api/v2/catalog/dodo_kwls7?latitude=53.9&longitude=27.5667",
    ]
    assert json.loads(зовы[0][1] or b"") == ТЕЛО


def _адреса(зовы: list[tuple[str, bytes | None]]) -> list[str]:
    return [url for url, _ in зовы]


def test_чужой_путь_и_кривое_тело_до_яндекса_не_доходят(
    ретранслятор: tuple[str, list[Any], dict[str, Any]],
) -> None:
    адрес, зовы, _ = ретранслятор
    assert _post(адрес, "/yandex/other", _тело(ТЕЛО)) == 404
    assert _post(адрес, "/stores/a", _тело(ТЕЛО)) == 404
    assert _post(адрес, "/yandex/search", _тело({**ТЕЛО, "url": "x"})) == 400
    assert _post(адрес, "/yandex/search", b"") == 400
    assert _post(адрес, "/yandex/search", b"x" * 2000) == 400
    assert _post(адрес, "/yandex/search", _тело(ТЕЛО)) == 200
    assert len(зовы) == 1


def test_get_на_поиск_и_чужой_хост_отказ(
    ретранслятор: tuple[str, list[Any], dict[str, Any]],
) -> None:
    адрес, зовы, _ = ретранслятор
    for путь in ("/yandex/search", "/yandex/catalog/../x?latitude=1&longitude=2"):
        with pytest.raises(urllib.error.HTTPError) as отказ:
            urllib.request.urlopen(адрес + путь)  # noqa: S310
        assert отказ.value.code == 404
    assert зовы == []


def test_429_яндекса_доходит_причиной_без_адреса(
    monkeypatch: pytest.MonkeyPatch, ретранслятор: tuple[str, list[Any], dict[str, Any]]
) -> None:
    адрес, _, ответ = ретранслятор
    ответ["status"] = 429
    with pytest.raises(AggregatorError) as отказ:
        yandex_eda.search(_http(monkeypatch, адрес), 53.9, 27.5667, "BY", {})
    assert str(отказ.value) == "Яндекс Еда ответила HTTP 429 (через домашний сервер)"
    assert "127.0.0.1" not in str(отказ.value)


def test_яндекс_недоступен_ретранслятор_502(
    monkeypatch: pytest.MonkeyPatch, ретранслятор: tuple[str, list[Any], dict[str, Any]]
) -> None:
    адрес, _, ответ = ретранслятор
    ответ["raise"] = urllib.error.URLError("dns")
    with pytest.raises(AggregatorError, match="Яндекс Еда ответила HTTP 502"):
        yandex_eda.search(_http(monkeypatch, адрес), 53.9, 27.5667, "BY", {})


def test_домашний_сервер_спит(monkeypatch: pytest.MonkeyPatch) -> None:
    сервер = HTTPServer(("127.0.0.1", 0), migros_relay.Handler)
    порт = сервер.server_port
    сервер.server_close()
    with pytest.raises(AggregatorError, match=r"^домашний сервер не отвечает"):
        yandex_eda.search(_http(monkeypatch, f"http://127.0.0.1:{порт}"), 53.9, 27.5, "BY", {})


def test_без_адреса_ходит_напрямую(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(migros.RELAY_VAR, raising=False)
    адреса: list[str] = []

    class Заглушка:
        def post(self, url: str, body: object, headers: object = None) -> object:
            адреса.append(url)
            return {}

    assert yandex_eda.search(Заглушка(), 1.0, 2.0, "BY", {}) == []  # type: ignore[arg-type]
    assert адреса == [yandex_eda.SEARCH]


def test_без_адреса_сбой_без_переписанной_причины(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(migros.RELAY_VAR, raising=False)

    class Лежит:
        def post(self, *_: object) -> object:
            raise AggregatorError("HTTP 429 — https://eda.yandex.by/x")

    with pytest.raises(AggregatorError, match=r"^HTTP 429 — https://eda"):
        yandex_eda.search(Лежит(), 1.0, 2.0, "BY", {})  # type: ignore[arg-type]


# --- пауза и включение ---


def test_без_адреса_яндекс_на_паузе() -> None:
    искать, пауза = collect.searchers(False)
    assert yandex_eda not in искать and пауза == (yandex_eda,)


def test_с_адресом_яндекс_в_сборе() -> None:
    искать, пауза = collect.searchers(True)
    assert искать[-1] is yandex_eda and пауза == ()
    assert искать[:-1] == collect._ALWAYS
