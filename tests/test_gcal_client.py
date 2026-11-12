"""Клиент Google Календаря (D740, #1590): что уходит в Google и как читаются отказы.

Сети нет: `opener` подменён двойником, который запоминает запросы. Проверяется то, что
делаем МЫ: событие на весь день в дату срока, без гостей, с уведомлением, без писем
(`sendUpdates=none`), отзыв ключа, коды причин без текста ответа.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from datetime import date
from typing import Any

import pytest

from src.gcal import client

КЛЮЧИ = client.ClientKeys("клиент", "секрет")


class Ответ:
    def __init__(self, тело: dict[str, Any] | None = None) -> None:
        self._тело = json.dumps(тело).encode() if тело is not None else b""

    def __enter__(self) -> Ответ:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._тело


class Двойник:
    """Отвечает по очереди; запросы запоминает."""

    def __init__(self, *ответы: object) -> None:
        self.ответы = list(ответы)
        self.запросы: list[Any] = []

    def __call__(self, запрос: Any, timeout: float) -> Ответ:
        self.запросы.append(запрос)
        ответ = self.ответы.pop(0)
        if isinstance(ответ, BaseException):
            raise ответ
        assert isinstance(ответ, Ответ)
        return ответ


def _отказ(код: int, тело: dict[str, Any] | None = None) -> urllib.error.HTTPError:
    сырое = json.dumps(тело or {}).encode()
    return urllib.error.HTTPError("https://x", код, "x", None, io.BytesIO(сырое))  # type: ignore[arg-type]


def test_событие_на_весь_день_без_гостей_и_с_уведомлением() -> None:
    тело = client.event_body(title="Название", description="Ссылка", due=date(2026, 11, 9))

    assert тело["start"] == {"date": "2026-11-09"}
    assert тело["end"] == {"date": "2026-11-10"}, "конец события на весь день — следующий день"
    assert "attendees" not in тело
    assert тело["reminders"] == {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": client.REMINDER_MINUTES_BEFORE_START}],
    }


def test_создание_не_шлёт_писем_и_берёт_основной_календарь() -> None:
    д = Двойник(Ответ({"id": "ev1"}))

    номер = client.create_event("токен", {"summary": "x"}, opener=д)

    assert номер == "ev1"
    запрос = д.запросы[0]
    адрес = urllib.parse.urlsplit(запрос.full_url)
    assert "/calendars/primary/events" in адрес.path
    assert urllib.parse.parse_qs(адрес.query) == {"sendUpdates": ["none"]}
    assert запрос.get_header("Authorization") == "Bearer токен"
    assert запрос.get_method() == "POST"


def test_ответ_без_номера_события_сбой_а_не_успех() -> None:
    with pytest.raises(client.CalendarError) as исход:
        client.create_event("т", {}, opener=Двойник(Ответ({})))
    assert исход.value.code == "no_event_id"


def test_перенос_это_patch_того_же_события() -> None:
    д = Двойник(Ответ({}))

    client.update_event("т", "ev/1", {"summary": "y"}, opener=д)

    assert д.запросы[0].get_method() == "PATCH"
    путь = urllib.parse.urlsplit(д.запросы[0].full_url).path
    assert путь.endswith("/events/ev%2F1"), путь


def test_удаление_уже_удалённого_события_не_сбой() -> None:
    client.delete_event(
        "т", "ev1", opener=Двойник(_отказ(410, {"error": {"errors": [{"reason": "deleted"}]}}))
    )
    client.delete_event("т", "ev1", opener=Двойник(_отказ(404)))


def test_удаление_с_другим_отказом_сбой() -> None:
    with pytest.raises(client.CalendarError) as исход:
        client.delete_event("т", "ev1", opener=Двойник(_отказ(500)))
    assert исход.value.code == "http_500"


def test_мёртвый_ключ_продления_называется_кодом_google() -> None:
    д = Двойник(_отказ(400, {"error": "invalid_grant", "error_description": "почта@x.y"}))

    with pytest.raises(client.CalendarError) as исход:
        client.access_token(КЛЮЧИ, "ключ", opener=д)

    assert исход.value.code == "invalid_grant"
    assert исход.value.code in client.DEAD_GRANT_CODES
    assert "почта" not in str(исход.value), "в код причины текст ответа Google не попадает"


def test_выключенный_api_виден_по_причине_из_тела() -> None:
    тело = {"error": {"status": "PERMISSION_DENIED", "errors": [{"reason": "accessNotConfigured"}]}}

    with pytest.raises(client.CalendarError) as исход:
        client.create_event("т", {}, opener=Двойник(_отказ(403, тело)))

    assert исход.value.code == "accessNotConfigured"


def test_отзыв_уже_мёртвого_ключа_считается_отзывом() -> None:
    client.revoke("к", opener=Двойник(_отказ(400, {"error": "invalid_token"})))


def test_отзыв_с_другим_отказом_поднимается() -> None:
    with pytest.raises(client.CalendarError):
        client.revoke("к", opener=Двойник(_отказ(503)))


def test_ключ_доступа_по_ключу_продления() -> None:
    д = Двойник(Ответ({"access_token": "короткий"}))

    assert client.access_token(КЛЮЧИ, "долгий", opener=д) == "короткий"
    форма = urllib.parse.parse_qs(д.запросы[0].data.decode())
    assert форма["grant_type"] == ["refresh_token"] and форма["refresh_token"] == ["долгий"]
