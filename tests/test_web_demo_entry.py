"""Открытое демо и лендинг (D524): вход без пароля есть только на стенде демо.

Ядро безопасности здесь одно: без `WEB_DEMO=1` маршрутов `/demo` нет вовсе, и
ни один из них не открывает сессию. Остальное — что лендинг виден
неопознанному и что вход в демо открывает сессию учётки выбранной роли.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask
from web_harness import СВОЙ, СЕКРЕТ, Учётка, подменить_двери

from src.domain.demo import DEMO_ROLES
from src.web import demo_entry
from src.web.app import create_app
from src.web.config import Settings, load_settings
from src.web.errors import WebConfigError


def _app(**настройки: Any) -> Flask:
    app = create_app(
        Settings(
            host="127.0.0.1", port=8266, tenant="HQ", ui_lang="en", secret_key=СЕКРЕТ, **настройки
        )
    )
    app.config.update(TESTING=True)
    return app


@pytest.mark.parametrize(
    ("метод", "адрес"),
    [("GET", "/demo"), ("GET", "/demo/app"), ("POST", "/demo/admin"), ("POST", "/demo/viewer")],
)
def test_без_переменной_демо_входа_нет(
    monkeypatch: pytest.MonkeyPatch, метод: str, адрес: str
) -> None:
    # Arrange
    двери = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    клиент = _app().test_client()

    # Act
    ответ = клиент.open(адрес, method=метод, headers={"Origin": СВОЙ})

    # Assert — неопознанного уводят на вход или отвечают 404, но сессии нет.
    assert ответ.status_code in (302, 404), ответ.status_code
    if ответ.status_code == 302:
        assert ответ.headers["Location"].startswith("/login"), ответ.headers["Location"]
    assert двери["open"] == [], "без WEB_DEMO открылась сессия"


def test_опечатка_в_переменной_демо_роняет_запуск() -> None:
    with pytest.raises(WebConfigError):
        load_settings({"WEB_DEMO": "yes", "WEB_SECRET_KEY": СЕКРЕТ})


def test_неопознанный_на_корне_видит_лендинг_без_демо() -> None:
    клиент = _app().test_client()
    корень = клиент.get("/?lang=en")
    assert корень.status_code == 302 and "/welcome" in корень.headers["Location"]
    страница = клиент.get("/welcome?lang=en").get_data(as_text=True)
    assert "Sign in" in страница and "Open the demo" not in страница


def test_лендинг_прода_ведёт_в_демо_по_адресу() -> None:
    клиент = _app(demo_url="https://demo.example").test_client()
    страница = клиент.get("/welcome?lang=ru").get_data(as_text=True)
    assert "Открыть демо" in страница and "https://demo.example" in страница


def test_на_стенде_демо_роль_открывает_сессию_своей_учётки(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    двери = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    роль = DEMO_ROLES[0]
    monkeypatch.setattr(
        demo_entry,
        "find_by_login",
        lambda login: Учётка(login=login, tenant=роль.tenant, role=роль.role),
    )
    monkeypatch.setattr(demo_entry, "open_session", lambda account, **_: двери_open(account))

    def двери_open(account: Учётка) -> Any:
        from src.web import auth

        return auth.open_session(account)

    клиент = _app(demo=True).test_client()

    # Act
    выбор = клиент.get("/demo?lang=en")
    вход = клиент.post(f"/demo/{роль.key}", headers={"Origin": СВОЙ})

    # Assert
    assert выбор.status_code == 200 and "Head office admin" in выбор.get_data(as_text=True)
    assert вход.status_code == 302, вход.get_data(as_text=True)[:300]
    assert двери["open"] == [роль.login]
    assert "Set-Cookie" in вход.headers


def test_чужая_роль_и_чужой_источник_не_входят(monkeypatch: pytest.MonkeyPatch) -> None:
    двери = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    клиент = _app(demo=True).test_client()
    assert клиент.post("/demo/root", headers={"Origin": СВОЙ}).status_code == 404
    assert клиент.post("/demo/admin", headers={"Origin": "https://evil.example"}).status_code == 403
    assert двери["open"] == []


def test_плашка_демо_только_на_стенде_демо() -> None:
    assert "Demo: made-up data" in _app(demo=True).test_client().get("/welcome?lang=en").get_data(
        as_text=True
    )
    assert "Demo: made-up data" not in _app().test_client().get("/welcome?lang=en").get_data(
        as_text=True
    )
