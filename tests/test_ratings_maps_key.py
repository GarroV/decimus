"""Ключ Pointer для загрузки оценок карт берётся через общее хранилище ключей (D576)."""

from __future__ import annotations

import pytest

from src.db import service_keys
from src.ratings import maps, pointer


def _перехват(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    ключи: list[str] = []
    monkeypatch.setattr(pointer, "http_fetch", lambda key: ключи.append(key) or (lambda _p: {}))
    return ключи


def test_ключ_pointer_берётся_из_базы_раньше_окружения(monkeypatch: pytest.MonkeyPatch) -> None:
    # Сломанная копия: вернуть в `_key_fetch` чтение `os.environ` — падает на ключе из окружения.
    monkeypatch.setenv("POINTER_API_KEY", "из-окружения")
    monkeypatch.setattr(
        service_keys, "stored", lambda name: "из-базы" if name == "pointer.api_key" else None
    )
    ключи = _перехват(monkeypatch)
    maps._key_fetch()
    assert ключи == ["из-базы"]


def test_ключ_pointer_без_записи_берётся_из_окружения(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POINTER_API_KEY", "из-окружения")
    monkeypatch.setattr(service_keys, "stored", lambda _name: None)
    ключи = _перехват(monkeypatch)
    maps._key_fetch()
    assert ключи == ["из-окружения"]


def test_нигде_нет_ключа_загрузка_выключена(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POINTER_API_KEY", raising=False)
    monkeypatch.setattr(service_keys, "stored", lambda _name: None)
    with pytest.raises(pointer.PointerError):
        maps._key_fetch()
