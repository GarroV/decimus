"""Язык сайта хранится за учёткой (D447); `?lang=` — разовый перекрёсток.

Порядок: язык в адресе → язык профиля → язык стенда. Пилюля вошедшего
сохраняет выбор в профиль и возвращает на ту же страницу; до входа пилюля —
ссылка с `?lang=`, как была. Слой базы подменён на границе.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.db import web_own_profile
from src.db.errors import AccessError
from src.web import auth

ЗАГОЛОВКИ = {"Origin": СВОЙ}


class Языки:
    def __init__(self) -> None:
        self.записано: list[tuple[str, str]] = []
        self.сбой = False

    def __call__(self, token: str, lang: str) -> bool:
        if self.сбой:
            raise AccessError("двойник: база молчит")
        self.записано.append((token, lang))
        return True


@pytest.fixture
def языки(monkeypatch: pytest.MonkeyPatch) -> Языки:
    двойник = Языки()
    monkeypatch.setattr(web_own_profile, "set_web_lang", двойник)
    return двойник


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, web_lang: str | None = None, role: str = "admin"
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role=role)
    with собрать(tenant="HQ", ui_lang="ru").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: (
                Учётка(tenant="HQ", role=role, web_lang=web_lang) if token == ТОКЕН else None
            ),
        )
        yield client


def test_язык_профиля_по_умолчанию(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, web_lang="en"):
        страница = client.get("/settings").get_data(as_text=True)

        assert "Interface language" in страница and "Язык интерфейса" not in страница


def test_язык_в_адресе_разово_поверх_профиля(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, web_lang="en"):
        страница = client.get("/settings?lang=ru").get_data(as_text=True)

        assert "Язык интерфейса" in страница


def test_без_выбора_язык_стенда(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch):
        assert "Язык интерфейса" in client.get("/settings").get_data(as_text=True)


def test_незаведённый_язык_профиля_не_роняет_страницу(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, web_lang="xx"):
        ответ = client.get("/settings")

        assert ответ.status_code == 200 and "Язык интерфейса" in ответ.get_data(as_text=True)


def test_выбор_сохраняется_и_возвращает_на_ту_же_страницу(
    monkeypatch: pytest.MonkeyPatch, языки: Языки
) -> None:
    for client in _стенд(monkeypatch, role="guest"):
        ответ = client.post(
            "/settings/lang",
            data={"lang": "en", "next": "/overview?country=RS"},
            headers=ЗАГОЛОВКИ,
        )

        assert ответ.status_code == 302
        assert ответ.headers["Location"] == "/overview?country=RS"
        assert языки.записано == [(ТОКЕН, "en")]


def test_незаведённый_язык_не_сохраняется(monkeypatch: pytest.MonkeyPatch, языки: Языки) -> None:
    for client in _стенд(monkeypatch):
        ответ = client.post("/settings/lang", data={"lang": "de"}, headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 302 and языки.записано == []


@pytest.mark.parametrize("назад", ["//evil.example/x", "https://evil.example", "\\\\evil", ""])
def test_возврат_только_внутрь_приложения(
    monkeypatch: pytest.MonkeyPatch, языки: Языки, назад: str
) -> None:
    for client in _стенд(monkeypatch):
        ответ = client.post(
            "/settings/lang", data={"lang": "en", "next": назад}, headers=ЗАГОЛОВКИ
        )

        assert ответ.headers["Location"] == "/settings"


def test_сбой_базы_меняет_язык_хотя_бы_этой_странице(
    monkeypatch: pytest.MonkeyPatch, языки: Языки
) -> None:
    языки.сбой = True
    for client in _стенд(monkeypatch):
        ответ = client.post(
            "/settings/lang", data={"lang": "en", "next": "/settings"}, headers=ЗАГОЛОВКИ
        )

        assert ответ.headers["Location"] == "/settings?lang=en"


def test_чужая_страница_язык_не_сохраняет(monkeypatch: pytest.MonkeyPatch, языки: Языки) -> None:
    for client in _стенд(monkeypatch):
        ответ = client.post(
            "/settings/lang", data={"lang": "en"}, headers={"Origin": "https://evil.example"}
        )

        assert ответ.status_code == 403 and языки.записано == []


def test_пилюля_вошедшего_сохраняет_а_до_входа_ссылка(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch):
        страница = client.get("/overview?country=RS&lang=ru").get_data(as_text=True)

        assert 'method="post" action="/settings/lang"' in страница
        assert 'name="next" value="/overview?country=RS"' in страница

    подменить_двери(monkeypatch, tenant="HQ")
    with собрать(tenant="HQ").test_client() as client:
        вход = client.get(auth.LOGIN_PATH).get_data(as_text=True)

    assert 'class="langpill" method="get"' in вход
