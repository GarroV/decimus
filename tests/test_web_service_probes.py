"""Проверки у провайдеров (D576): что уходит наружу и как читается ответ. Сеть подменена."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from src.health import probes as service_probes
from src.health.probes import KeyRejected, KeyUnverified


class _Ответ(io.BytesIO):
    def __enter__(self) -> _Ответ:
        return self

    def __exit__(self, *_a: Any) -> None:
        return None


def _подменить(monkeypatch: pytest.MonkeyPatch, результат: Any) -> list[urllib.request.Request]:
    зовы: list[urllib.request.Request] = []

    def open_(request: urllib.request.Request, timeout: float) -> Any:
        зовы.append(request)
        assert timeout == service_probes.TIMEOUT_SEC
        if isinstance(результат, Exception):
            raise результат
        return _Ответ(json.dumps(результат).encode())

    monkeypatch.setattr(service_probes._opener, "open", open_)
    return зовы


def _http(code: int, тело: bytes | None = None) -> urllib.error.HTTPError:
    fp = None if тело is None else io.BytesIO(тело)
    return urllib.error.HTTPError("https://x", code, "x", {}, fp)  # type: ignore[arg-type]


def test_ispring_шлёт_client_credentials_на_постоянный_хост(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    зовы = _подменить(monkeypatch, {"access_token": "t"})
    service_probes.probe_ispring({"client_id": "cid", "client_secret": "sec"})
    запрос = зовы[0]
    assert запрос.full_url == "https://api-learn.ispring.com/api/v3/token"
    assert запрос.get_method() == "POST"
    assert запрос.data == b"grant_type=client_credentials&client_id=cid&client_secret=sec"


@pytest.mark.parametrize("код", [400, 401, 403])
def test_ispring_неверная_пара_отказ(monkeypatch: pytest.MonkeyPatch, код: int) -> None:
    _подменить(monkeypatch, _http(код))
    with pytest.raises(KeyRejected) as exc:
        service_probes.probe_ispring({"client_id": "a", "client_secret": "b"})
    assert exc.value.status == код


@pytest.mark.parametrize(
    "сбой", [_http(500), _http(429), TimeoutError(), urllib.error.URLError("x")]
)
def test_ispring_сбой_провайдера_не_значит_неверный_ключ(
    monkeypatch: pytest.MonkeyPatch, сбой: Exception
) -> None:
    _подменить(monkeypatch, сбой)
    with pytest.raises(KeyUnverified):
        service_probes.probe_ispring({"client_id": "a", "client_secret": "b"})


def test_ispring_ответ_без_токена_не_проверка(monkeypatch: pytest.MonkeyPatch) -> None:
    _подменить(monkeypatch, {"nothing": 1})
    with pytest.raises(KeyUnverified):
        service_probes.probe_ispring({"client_id": "a", "client_secret": "b"})


def test_pointer_идёт_дешёвым_вызовом_с_ключом_в_заголовке(monkeypatch: pytest.MonkeyPatch) -> None:
    зовы = _подменить(monkeypatch, {"items": []})
    service_probes.probe_pointer({"api_key": "k-1"})
    assert зовы[0].full_url.endswith("/networks?limit=1&offset=0")
    assert зовы[0].get_header("Authorization") == "Bearer k-1"


def test_pointer_401_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    _подменить(monkeypatch, _http(401))
    with pytest.raises(KeyRejected):
        service_probes.probe_pointer({"api_key": "k"})


@pytest.mark.parametrize(
    "тело",
    [
        '{"error":"слишком много запросов, попробуйте позже"}'.encode(),
        b'{"error":"Too Many Requests"}',
    ],
)
def test_pointer_лимит_кодом_400_не_отказ_в_ключе(
    monkeypatch: pytest.MonkeyPatch, тело: bytes
) -> None:
    # #1256: Pointer отдаёт упор в лимит кодом 400; верный ключ не должен стать красным.
    _подменить(monkeypatch, _http(400, тело))
    with pytest.raises(KeyUnverified):
        service_probes.probe_pointer({"api_key": "k"})


def test_pointer_400_с_другим_телом_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    _подменить(monkeypatch, _http(400, b'{"error":"invalid token"}'))
    with pytest.raises(KeyRejected):
        service_probes.probe_pointer({"api_key": "k"})


def test_перенаправление_не_выполняется() -> None:
    обработчик = service_probes._NoRedirect()
    assert obrabotchik_redirect(обработчик) is None


def obrabotchik_redirect(h: service_probes._NoRedirect) -> Any:
    return h.redirect_request()
