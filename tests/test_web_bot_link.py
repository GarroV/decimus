"""D286: человек сам привязывает бота к своей учётке; ссылка — только своей учётке.

Review Focus 1–3 волны 1 (#340) на стороне веба: ссылку выпускают вошедшему и
только ему (ключ учётки из формы не читается), показывают один раз на странице,
а не в адресе; свою привязку отвязывает каждый, чужую — только админ УК.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.db import bot_links

БОТ = "decimus_test_bot"
ЗАГОЛОВКИ = {"Origin": СВОЙ}


@pytest.fixture
def выпуски(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    кому: list[str] = []

    def выпуск(user_id: str) -> bot_links.IssuedLink:
        кому.append(user_id)
        return bot_links.IssuedLink(token="t0k3n", expires_at=datetime.now(UTC))

    monkeypatch.setattr(bot_links, "issue_link", выпуск)
    return кому


def test_ссылка_выпускается_вошедшему_и_показывается_на_странице(
    выпуски: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ", bot_username=БОТ).test_client() as client:
        войти(client)
        ответ = client.post("/users/bot-link", headers=ЗАГОЛОВКИ, data={"user_id": "чужой-id"})
    assert выпуски == [Учётка().id], "ссылка выпущена не своей учётке"
    assert f"https://t.me/{БОТ}?start=link-t0k3n" in ответ.get_data(as_text=True)
    assert "t0k3n" not in (ответ.headers.get("Location") or "")


def test_ссылка_не_выпускается_с_чужой_страницы(
    выпуски: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ", bot_username=БОТ).test_client() as client:
        войти(client)
        client.post("/users/bot-link", headers={"Origin": "https://evil.example"})
    assert выпуски == []


def test_без_имени_бота_ссылки_нет_и_переменная_названа(
    выпуски: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        страница = client.get("/users").get_data(as_text=True)
        ответ = client.post("/users/bot-link", headers=ЗАГОЛОВКИ)
    assert "WEB_BOT_USERNAME" in страница and "/users/bot-link" not in страница
    assert ответ.status_code == 503 and выпуски == []


def test_привязанный_видит_свой_telegram_и_может_отвязать(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    привязка = bot_links.Binding(
        telegram_id=501,
        user_id=Учётка().id,
        login="director",
        tenant="GE",
        bound_at=datetime(2026, 10, 1, 9, 30, tzinfo=UTC),
    )
    отвязано: list[str] = []
    подменить_двери(monkeypatch, tenant="GE")
    monkeypatch.setattr(bot_links, "binding_of", lambda _u: привязка)
    monkeypatch.setattr(bot_links, "unbind", lambda u: отвязано.append(u) or True)
    with собрать(tenant="HQ", bot_username=БОТ).test_client() as client:
        войти(client)
        страница = client.get("/users").get_data(as_text=True)
        ответ = client.post("/users/bot-unlink", headers=ЗАГОЛОВКИ)
    assert "501" in страница and "2026-10-01 09:30" in страница
    assert ответ.status_code == 200 and отвязано == [Учётка().id]


def test_чужую_привязку_отвязывает_только_админ_уК(monkeypatch: pytest.MonkeyPatch) -> None:
    отвязано: list[Any] = []
    monkeypatch.setattr(bot_links, "unbind", lambda u: отвязано.append(u) or True)
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/bot-unlink", headers=ЗАГОЛОВКИ, data={"user_id": "другой"})
    assert ответ.status_code == 403 and отвязано == []


def test_админ_уК_отвязывает_чужую_привязку(monkeypatch: pytest.MonkeyPatch) -> None:
    отвязано: list[Any] = []
    monkeypatch.setattr(bot_links, "unbind", lambda u: отвязано.append(u) or True)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    monkeypatch.setattr("src.web.accounts.everyone", lambda **_k: ())
    monkeypatch.setattr("src.web.accounts.spaces", lambda: ("HQ", "GE"))
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/bot-unlink", headers=ЗАГОЛОВКИ, data={"user_id": "другой"})
    assert ответ.status_code == 200 and отвязано == ["другой"]
