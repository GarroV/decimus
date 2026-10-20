"""Откуда `recognize` берёт ключ модели (D491): база → окружение, кэш на минуту.

Порядок — ядро: подмена порядка молча уводит разбор на чужой ключ. Каждая проверка
прогонялась на сломанной копии (порядок переставлен — падает `test_база_раньше_окружения`).
"""

from __future__ import annotations

import pytest

from src.db import model_key, service_keys
from src.recognize import config

ИЗ_БАЗЫ = "sk-from-database-1111"
ИЗ_ОКРУЖЕНИЯ = "sk-from-env-2222"


@pytest.fixture(autouse=True)
def _чистый_кэш(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_keys, "_cache", {})
    monkeypatch.setenv(config.API_KEY_VAR, ИЗ_ОКРУЖЕНИЯ)


def test_база_раньше_окружения(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_keys, "_read_decrypted", lambda _name: ИЗ_БАЗЫ)
    assert config.load_recognize_settings().api_key == ИЗ_БАЗЫ


def test_в_базе_пусто_работает_окружение(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_keys, "_read_decrypted", lambda _name: None)
    assert config.load_recognize_settings().api_key == ИЗ_ОКРУЖЕНИЯ


def test_сбой_базы_не_роняет_разбор_работает_окружение(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def упала(_name: str) -> str:
        raise service_keys.AccessError("нет связи")

    monkeypatch.setattr(service_keys, "_read_decrypted", упала)
    assert config.load_recognize_settings().api_key == ИЗ_ОКРУЖЕНИЯ
    assert ИЗ_ОКРУЖЕНИЯ not in caplog.text and ИЗ_БАЗЫ not in caplog.text


def test_явное_окружение_базы_не_касается(monkeypatch: pytest.MonkeyPatch) -> None:
    def не_звать(_name: str) -> str:
        raise AssertionError("база прочитана при явном окружении")

    monkeypatch.setattr(service_keys, "_read_decrypted", не_звать)
    got = config.load_recognize_settings({config.API_KEY_VAR: "sk-explicit"})
    assert got.api_key == "sk-explicit"


def test_кэш_живёт_минуту_и_не_дольше(monkeypatch: pytest.MonkeyPatch) -> None:
    часы = [1000.0]
    чтений: list[int] = []
    значение = [ИЗ_БАЗЫ]

    def читать(_name: str) -> str:
        чтений.append(1)
        return значение[0]

    monkeypatch.setattr(service_keys.time, "monotonic", lambda: часы[0])
    monkeypatch.setattr(service_keys, "_read_decrypted", читать)
    assert config.resolve_api_key() == ИЗ_БАЗЫ
    значение[0] = "sk-rotated-3333"
    часы[0] += model_key.CACHE_SECONDS - 1
    assert config.resolve_api_key() == ИЗ_БАЗЫ, "внутри минуты — из кэша"
    assert len(чтений) == 1
    часы[0] += 2
    assert config.resolve_api_key() == "sk-rotated-3333", "после минуты — свежее значение"
    assert len(чтений) == 2
