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
        # GET — на посадочную (D544), POST — на форму входа.
        ждём = "/welcome" if метод == "GET" else "/login"
        assert ответ.headers["Location"].startswith(ждём), ответ.headers["Location"]
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


def test_в_демо_общие_учётки_не_портятся(monkeypatch: pytest.MonkeyPatch) -> None:
    """Один посетитель не ломает вход остальным: способы входа и учётки — не трогаются."""
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    app = _app(demo=True)
    адреса = {
        r.endpoint: (r.rule, "POST" if "POST" in (r.methods or set()) else "GET")
        for r in app.url_map.iter_rules()
        if r.endpoint in demo_entry.LOCKED_ENDPOINTS and "<" not in r.rule
    }
    assert адреса, "выключенных действий не нашлось на карте маршрутов"
    клиент = app.test_client()
    for конец, (путь, метод) in адреса.items():
        ответ = клиент.open(путь, method=метод, headers={"Origin": СВОЙ})
        assert ответ.status_code == 403, f"{конец} {путь} в демо не выключен"


def test_выключенные_в_демо_действия_есть_в_продукте() -> None:
    """Опечатка в списке молча оставила бы действие открытым."""
    конечные = {r.endpoint for r in _app(demo=True).url_map.iter_rules()}
    assert demo_entry.LOCKED_ENDPOINTS <= конечные, demo_entry.LOCKED_ENDPOINTS - конечные


def test_каждое_действие_продукта_разобрано_для_демо() -> None:
    """Новое действие не проскочит в демо молча: оно выключено или названо открытым."""
    # Arrange
    действия = {
        r.endpoint
        for r in _app(demo=True).url_map.iter_rules()
        if (r.methods or set()) - {"GET", "HEAD", "OPTIONS"}
    }
    разобрано = demo_entry.LOCKED_ENDPOINTS | demo_entry.OPEN_ENDPOINTS

    # Assert
    assert not действия - разобрано, f"не решено, работает ли в демо: {действия - разобрано}"
    assert not demo_entry.LOCKED_ENDPOINTS & demo_entry.OPEN_ENDPOINTS
    assert demo_entry.OPEN_ENDPOINTS <= действия, demo_entry.OPEN_ENDPOINTS - действия


@pytest.mark.parametrize("путь", ["/login/google", "/auth/google/callback", "/auth/google/mail"])
def test_в_демо_google_выключен_и_для_get(monkeypatch: pytest.MonkeyPatch, путь: str) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    ответ = _app(demo=True).test_client().get(путь)
    assert ответ.status_code == 403, f"{путь} в демо открыт: {ответ.status_code}"
