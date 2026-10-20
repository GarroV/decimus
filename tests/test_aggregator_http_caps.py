"""F-126: `Http._call` читает ответ с потолком размера и укладывается в общий срок."""

from __future__ import annotations

import io
import urllib.error
from typing import Any

import pytest

from src.ratings.aggregators import base
from src.ratings.aggregators.base import AggregatorError, Http

URL = "https://example.com/api"


class _Resp(io.BytesIO):
    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_a: Any) -> None:
        self.close()


@pytest.fixture(autouse=True)
def _без_пауз(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base.time, "sleep", lambda _s: None)


def _json_of_size(n: int) -> bytes:
    pad = n - len(b'{"a":""}')
    return b'{"a":"' + b"x" * pad + b'"}'


def test_body_exactly_at_cap_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "BODY_MAX_BYTES", 1000)
    monkeypatch.setattr(
        base.urllib.request, "urlopen", lambda *_a, **_k: _Resp(_json_of_size(1000))
    )
    assert Http(0).get(URL) == {"a": "x" * (1000 - 8)}


def test_body_over_cap_is_refused_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(base, "BODY_MAX_BYTES", 1000)
    calls = 0

    def opener(*_a: Any, **_k: Any) -> _Resp:
        nonlocal calls
        calls += 1
        return _Resp(_json_of_size(1001))

    monkeypatch.setattr(base.urllib.request, "urlopen", opener)
    with pytest.raises(AggregatorError, match="больше 1000 байт"):
        Http(0).get(URL)
    assert calls == 1


def test_deadline_stops_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr(base.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(base.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    attempts = 0

    def failing(*_a: Any, **_k: Any) -> Any:
        nonlocal attempts
        attempts += 1
        clock[0] += 60  # каждая попытка висит минуту
        raise urllib.error.HTTPError(URL, 503, "busy", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(base.urllib.request, "urlopen", failing)
    monkeypatch.setattr(base, "DEADLINE_SEC", 100.0)
    with pytest.raises(AggregatorError, match="общий срок"):
        Http(0).get(URL)
    assert attempts == 2  # третья не начата: 60 + 15 + 60 + 30 > 100
