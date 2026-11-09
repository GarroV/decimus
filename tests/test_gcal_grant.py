"""Отключение календаря (D741, #1590): ключ отзывается у Google до стирания у нас.

Сети и базы нет: Google — двойник `opener`, база — двойник `calendar_store`. Главное правило:
стёртая запись не должна оставлять действующий доступ незамеченным — либо отозван, либо человеку
сказано отозвать самому.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from typing import Any

import pytest

from src.db import calendar_store, secret_crypto
from src.gcal import client, grant

КЛЮЧИ = client.ClientKeys("клиент", "секрет")


class Ответ:
    def __enter__(self) -> Ответ:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return b"{}"


class Google:
    def __init__(self) -> None:
        self.пути: list[str] = []
        self.отзыв_падает = False

    def __call__(self, запрос: Any, timeout: float) -> Ответ:
        путь = urllib.parse.urlsplit(запрос.full_url).path
        self.пути.append(путь)
        if путь == "/revoke" and self.отзыв_падает:
            raise urllib.error.HTTPError(
                "https://x",
                503,
                "x",
                None,
                io.BytesIO(json.dumps({}).encode()),  # type: ignore[arg-type]
            )
        return Ответ()


class База:
    def __init__(self) -> None:
        self.подключение: calendar_store.Grant | None = calendar_store.Grant(
            "u", "a@x.y", "s", None
        )
        self.ключ: str | None = "долгий"
        self.не_открывается = False
        self.стёрто = False

    def grant_of(self, user_id: str) -> calendar_store.Grant | None:
        return self.подключение

    def refresh_token_of(self, user_id: str) -> str | None:
        if self.не_открывается:
            raise secret_crypto.SecretCryptoError("двойник")
        return self.ключ

    def events_of(self, user_id: str) -> list[calendar_store.Orphan]:
        return []

    def delete_grant(self, user_id: str) -> bool:
        self.стёрто = True
        return True


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> База:
    двойник = База()
    for имя in ("grant_of", "refresh_token_of", "events_of", "delete_grant"):
        monkeypatch.setattr(calendar_store, имя, getattr(двойник, имя))
    monkeypatch.setattr(client, "REVOKE_ENDPOINT", "https://oauth.test/revoke")
    monkeypatch.delenv(client.GOOGLE_CLIENT_ID_VAR, raising=False)
    return двойник


def test_отзыв_идёт_и_без_реквизитов_клиента(база: База) -> None:
    """`/revoke` принимает один токен: нет GOOGLE_CLIENT_ID/SECRET — не повод оставить доступ."""
    google = Google()

    итог = grant.disconnect("u", opener=google)

    assert итог == grant.OFF and google.пути == ["/revoke"]
    assert база.стёрто


def test_с_реквизитами_отзыв_тоже_идёт(база: База) -> None:
    google = Google()

    assert grant.disconnect("u", keys=КЛЮЧИ, opener=google) == grant.OFF
    assert "/revoke" in google.пути


def test_неотозванный_ключ_оставляет_подключение(база: База) -> None:
    google = Google()
    google.отзыв_падает = True

    итог = grant.disconnect("u", opener=google)

    assert итог == grant.FAILED and not база.стёрто


def test_ключ_не_открылся_запись_стёрта_а_человеку_сказано_отозвать_самому(база: База) -> None:
    база.не_открывается = True
    google = Google()

    итог = grant.disconnect("u", keys=КЛЮЧИ, opener=google)

    assert итог == grant.REVOKE_MANUALLY, "молчаливое «отключено» оставило бы доступ незамеченным"
    assert база.стёрто and google.пути == []


def test_не_подключённому_нечего_отключать(база: База) -> None:
    база.подключение = None

    assert grant.disconnect("u", opener=Google()) == grant.NONE
