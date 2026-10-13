"""Меню учётки и своё фото (D468) — уровень страниц.

Базы нет: двери опознания и чтения подменены. Ядро здесь — доступ: фото отдаётся
ТОЛЬКО вошедшему и ТОЛЬКО его собственное, чужое по ключу не отдаётся вовсе.
Остальное — что человек видит: имя вместо логина, фото вместо инициалов, меню
с подключениями, выход формой.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from web_harness import ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.db import mcp_access, oauth_store, web_own_profile
from src.db.errors import AccessError
from src.web import auth

JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes-of-director"
ЧУЖОЙ_ТОКЕН = "сессия-другого-человека"
ЧУЖОЕ = b"\xff\xd8\xff\xe0" + b"jpeg-bytes-of-somebody-else"
ВЕРСИЯ = "0123456789abcdef"


class Фото:
    """Двойник `own_avatar`: как база, выбирает строку по ТОКЕНУ сессии, не по ключу."""

    def __init__(self) -> None:
        self.по_токенам: dict[str, tuple[bytes, str, str]] = {
            ТОКЕН: (JPEG, "image/jpeg", ВЕРСИЯ),
            ЧУЖОЙ_ТОКЕН: (ЧУЖОЕ, "image/jpeg", "fedcba9876543210"),
        }
        self.звали: list[str] = []
        self.сбой = False

    def __call__(self, token: str) -> tuple[bytes, str, str] | None:
        self.звали.append(token)
        if self.сбой:
            raise AccessError("двойник: база молчит")
        return self.по_токенам.get(token)


@pytest.fixture
def фото(monkeypatch: pytest.MonkeyPatch) -> Фото:
    двойник = Фото()
    monkeypatch.setattr(web_own_profile, "own_avatar", двойник)
    return двойник


def _стенд(monkeypatch: pytest.MonkeyPatch, **учётка: object) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: Учётка(tenant="HQ", role="admin", **учётка) if token == ТОКЕН else None,  # type: ignore[arg-type]
        )
        yield client


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch)


@pytest.fixture
def клиент_с_google(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(
        monkeypatch, display_name="Иван Петров", avatar_etag=ВЕРСИЯ, email="ivan@dodobrands.io"
    )


# ── Своё фото: ядро доступа ───────────────────────────────────────────


def test_фото_отдаётся_вошедшему_и_закрыто_для_общего_кэша(клиент: FlaskClient, фото: Фото) -> None:
    ответ = клиент.get("/settings/avatar")

    assert ответ.status_code == 200
    assert ответ.data == JPEG
    assert ответ.mimetype == "image/jpeg"
    assert ответ.headers["Cache-Control"].startswith("private")
    assert ответ.headers["ETag"] == f'"{ВЕРСИЯ}"'
    assert ответ.headers["X-Content-Type-Options"] == "nosniff"


def test_фото_выбирается_по_сессии_запроса_а_не_по_адресу(клиент: FlaskClient, фото: Фото) -> None:
    """Чужое по ключу не отдаётся: ни `?user=`, ни `?id=`, ни путь не называют учётку."""
    for запрос in ("?user=2", "?id=22222222-2222-2222-2222-222222222222", "?token=" + ЧУЖОЙ_ТОКЕН):
        ответ = клиент.get("/settings/avatar" + запрос)

        assert ответ.data == JPEG, "по параметру запроса отдали чужое фото"
    assert set(фото.звали) == {ТОКЕН}, "база спрошена не про токен своей сессии"
    assert клиент.get("/settings/avatar/22222222-2222-2222-2222-222222222222").status_code == 404


def test_без_входа_фото_не_отдаётся(фото: Фото, monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as аноним:
        ответ = аноним.get("/settings/avatar")

    assert ответ.status_code in (302, 401, 403)
    assert JPEG not in ответ.data
    assert фото.звали == []


def test_нет_фото_значит_404(клиент: FlaskClient, фото: Фото) -> None:
    фото.по_токенам.pop(ТОКЕН)

    assert клиент.get("/settings/avatar").status_code == 404


def test_повторный_запрос_с_той_же_версией_отвечает_304(клиент: FlaskClient, фото: Фото) -> None:
    ответ = клиент.get("/settings/avatar", headers={"If-None-Match": f'"{ВЕРСИЯ}"'})

    assert ответ.status_code == 304
    assert ответ.data == b""


def test_отказ_базы_даёт_503_а_не_падение(клиент: FlaskClient, фото: Фото) -> None:
    фото.сбой = True

    assert клиент.get("/settings/avatar").status_code == 503


# ── Блок учётки и меню на странице ───────────────────────────────────


def test_имя_и_фото_вместо_логина_и_инициалов(клиент_с_google: FlaskClient) -> None:
    страница = клиент_с_google.get("/settings").get_data(as_text=True)

    assert "<b>Иван Петров</b>" in страница
    assert f"/settings/avatar?v={ВЕРСИЯ}" in страница
    assert "ivan@dodobrands.io" in страница


def test_без_google_логин_и_инициалы(клиент: FlaskClient) -> None:
    страница = клиент.get("/settings").get_data(as_text=True)

    assert "<b>director</b>" in страница
    assert "/settings/avatar" not in страница
    assert ">DI<" in страница.replace(" ", "").replace("\n", "")


def test_имя_без_фото_даёт_инициалы_имени(monkeypatch: pytest.MonkeyPatch) -> None:
    for клиент in _стенд(monkeypatch, display_name="Иван Петров"):
        страница = клиент.get("/settings").get_data(as_text=True)

        assert ">ИП<" in страница.replace(" ", "").replace("\n", "")
        assert "/settings/avatar" not in страница


def test_имя_в_разметке_экранируется(monkeypatch: pytest.MonkeyPatch) -> None:
    for клиент in _стенд(monkeypatch, display_name="<img src=x onerror=alert(1)>"):
        страница = клиент.get("/settings").get_data(as_text=True)

        assert "<img src=x onerror" not in страница


def test_блок_учётки_открывает_меню_а_без_скрипта_ведёт_в_настройки(
    клиент_с_google: FlaskClient,
) -> None:
    страница = клиент_с_google.get("/settings").get_data(as_text=True)

    assert страница.count("data-acct-menu") == 2, "ожидались панель и полоса телефона"
    assert 'id="acct-menu"' in страница
    assert 'role="menu"' in страница
    assert 'class="sidenav__me" href="/settings?lang=ru"' in страница


def test_в_меню_тема_язык_все_настройки_и_выход_формой(клиент_с_google: FlaskClient) -> None:
    страница = клиент_с_google.get("/settings").get_data(as_text=True)
    меню = страница[страница.index('id="acct-menu"') :]
    меню = меню[: меню.index("</nav>")] if "</nav>" in меню else меню

    assert "data-theme-value" in меню
    assert "langpill" in меню
    assert "Все настройки" in меню
    assert '<form class="acct-menu__logout" method="post"' in меню
    for якорь in ("#claude", "#bot", "#google"):
        assert якорь in меню


def test_строки_темы_и_языка_убраны_из_подвала_панели(клиент: FlaskClient) -> None:
    страница = клиент.get("/settings").get_data(as_text=True)

    assert "sidenav__prefs" not in страница
    assert 'class="logout"' not in страница, "стрелка выхода осталась в блоке учётки"


def test_меню_на_английском(monkeypatch: pytest.MonkeyPatch) -> None:
    for клиент in _стенд(monkeypatch):
        страница = клиент.get("/settings?lang=en").get_data(as_text=True)

        assert "All settings" in страница and "Connections" in страница
        assert "Sign out" in страница
        assert "Все настройки" not in страница


# ── Подключения: фрагмент ─────────────────────────────────────────────


@pytest.fixture
def состояния(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from src.db import bot_links

    данные = {"токен": None, "подключения": [], "бот": None}
    monkeypatch.setattr(mcp_access, "live_token_expiry", lambda _id: данные["токен"])
    monkeypatch.setattr(oauth_store, "list_connections", lambda _id: данные["подключения"])
    monkeypatch.setattr(bot_links, "binding_of", lambda _id: данные["бот"])
    return данные


def test_фрагмент_ничего_не_подключено(клиент: FlaskClient, состояния: dict) -> None:  # type: ignore[type-arg]
    ответ = клиент.get("/settings/menu")
    текст = ответ.get_data(as_text=True)

    assert ответ.status_code == 200
    assert ответ.headers["Cache-Control"] == "no-store"
    assert текст.count("Не подключено") == 3
    assert "</span>Подключено</span>" not in текст


def test_фрагмент_показывает_подключённое_словом_и_точкой(
    клиент: FlaskClient,
    состояния: dict,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[type-arg]
) -> None:
    from datetime import UTC, datetime

    состояния["токен"] = datetime(2030, 1, 1, tzinfo=UTC)
    состояния["бот"] = object()

    текст = клиент.get("/settings/menu").get_data(as_text=True)

    assert текст.count("</span>Подключено</span>") == 2
    assert текст.count("</span>Не подключено</span>") == 1
    assert текст.count("acct-dot--ok") == 2


def test_фрагмент_без_входа_не_отдаётся(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as аноним:
        ответ = аноним.get("/settings/menu")

    assert ответ.status_code in (302, 401, 403)
    assert "acct-menu" not in ответ.get_data(as_text=True)


def test_молчание_базы_это_не_знаем_а_не_не_подключено(
    клиент: FlaskClient,
    состояния: dict,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[type-arg]
) -> None:
    from src.db import bot_links

    def молчит(_id: str) -> object:
        raise AccessError("двойник: база молчит")

    monkeypatch.setattr(bot_links, "binding_of", молчит)

    текст = клиент.get("/settings/menu").get_data(as_text=True)

    assert "Не удалось узнать" in текст


@pytest.mark.parametrize(
    ("tenant", "role"),
    [("GE", "auditor"), ("HQ", "control"), ("HQ", "admin"), ("GE", "admin")],
)
def test_фото_и_меню_открыты_любой_роли_и_пространству(
    monkeypatch: pytest.MonkeyPatch,
    фото: Фото,
    состояния: dict,
    tenant: str,
    role: str,  # type: ignore[type-arg]
) -> None:
    """Это дела человека над своей учёткой: партнёр и контроль не получают 404."""
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302

        assert client.get("/settings/avatar").status_code == 200
        assert client.get("/settings/menu").status_code == 200
