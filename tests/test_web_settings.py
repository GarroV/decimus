"""Экран «Настройки» (D447): один набор своего профиля для любой роли.

Права — ядро: «Настройки» открыты каждому вошедшему, но дела в них — только
СВОИ, а гость на запись не допущен нигде, кроме пароля и своего Claude. Слой
базы подменён на границе, как в соседних наборах.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.web import auth
from src.web.google_auth import GoogleSettings

ЗАГОЛОВКИ = {"Origin": СВОЙ}
МОЙ_ID = Учётка().id
ПОЧТА = "person@example.test"

#: Каждая роль, которой открыт вход: у контроля и гостя УК свои заслоны на разделы.
РОЛИ = [
    ("HQ", "superadmin"),
    ("HQ", "admin"),
    ("HQ", "control"),
    ("HQ", "guest"),
    ("HQ", "auditor"),
    ("GE", "admin"),
    ("GE", "auditor"),
]

РАЗДЕЛЫ = ('id="claude"', 'id="bot"', 'id="google"', 'id="language"', 'id="password"')


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, **настройки: str
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ", **настройки).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_настройки_открыты_каждой_роли_одним_набором(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.get("/settings")
        страница = ответ.get_data(as_text=True)

        assert ответ.status_code == 200, (tenant, role)
        for раздел in РАЗДЕЛЫ:
            assert раздел in страница, (tenant, role, раздел)
        assert 'href="/settings?lang=' in страница, "из меню учётки в настройки пути нет"
        assert ответ.headers["Cache-Control"] == "no-store", "токен и ссылку кэшируют"


def test_раздела_настроек_в_левой_панели_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/overview").get_data(as_text=True)

        assert 'class="sidenav__label">Настройки' not in страница
        assert 'class="sidenav__me" href="/settings' in страница


def test_без_входа_настройки_не_открываются(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        ответ = client.get("/settings")

    assert ответ.status_code == 302 and "/login" in ответ.headers["Location"]


def test_своя_карточка_ведёт_в_настройки_и_копий_не_держит(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/users?person=me").get_data(as_text=True)

        assert 'href="/settings' in страница
        for копия in ("/settings/password", 'name="current"', "claude-token", "bot-link"):
            assert копия not in страница, f"на карточке осталась копия: {копия}"


@pytest.mark.parametrize("дверь", ["/users/password", "/users/claude-token", "/users/bot-link"])
def test_старых_дверей_своих_дел_на_пользователях_нет(
    monkeypatch: pytest.MonkeyPatch, дверь: str
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        assert client.post(дверь, headers=ЗАГОЛОВКИ).status_code in (404, 405)


def test_свою_привязку_на_пользователях_не_снять(monkeypatch: pytest.MonkeyPatch) -> None:
    """Одно дело — одна дверь: свой бот отвязывается в «Настройках», не на карточке людей."""
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        for форма in ({}, {"user_id": МОЙ_ID}):
            ответ = client.post("/users/bot-unlink", headers=ЗАГОЛОВКИ, data=форма)
            assert ответ.status_code == 403, форма


def test_гость_бота_не_привязывает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="guest", bot_username="decimus_bot"):
        страница = client.get("/settings").get_data(as_text=True)

        assert "/settings/bot-link" not in страница, "гостю нарисована кнопка бота"
        assert client.post("/settings/bot-link", headers=ЗАГОЛОВКИ).status_code == 403
        assert client.post("/settings/bot-unlink", headers=ЗАГОЛОВКИ).status_code == 403


def test_контролю_настройки_открыты_а_проверки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="control", bot_username="decimus_bot"):
        assert client.get("/settings").status_code == 200
        assert client.get("/inspections").status_code == 404, "заслон контролинга ослаблен"


def test_бот_без_имени_называет_переменную(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="auditor"):
        страница = client.get("/settings").get_data(as_text=True)

        assert "WEB_BOT_USERNAME" in страница and "/settings/bot-link" not in страница


def test_адрес_mcp_берётся_из_настройки_стенда(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(
        monkeypatch,
        tenant="HQ",
        role="auditor",
        admin_public_url="https://admin.example",
        mcp_public_url="https://mcp.example/mcp",
    ):
        страница = client.get("/settings").get_data(as_text=True)

        assert "claude mcp add --transport http decimus https://mcp.example/mcp" in страница


def _с_почтой(monkeypatch: pytest.MonkeyPatch, *, google: bool) -> Iterator[FlaskClient]:
    """Вошедший с привязанной почтой. Входит без неё: с почтой паролем вход закрыт (D450)."""
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    if google:
        реквизиты = GoogleSettings(client_id="c", client_secret="s", redirect_uri="https://x/cb")
        monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: реквизиты)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: (
                Учётка(tenant="HQ", role="admin", email=ПОЧТА) if token == ТОКЕН else None
            ),
        )
        yield client


def test_с_почтой_и_google_пароль_закрыт_и_так_сказано(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _с_почтой(monkeypatch, google=True):
        страница = client.get("/settings").get_data(as_text=True)

        assert ПОЧТА in страница
        assert 'name="current"' not in страница, "форма смены пароля при закрытом входе паролем"
        assert "Вход паролем для этой учётки закрыт" in страница


def test_с_почтой_без_google_пароль_остаётся(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _с_почтой(monkeypatch, google=False):
        страница = client.get("/settings").get_data(as_text=True)

        assert ПОЧТА in страница and 'name="current"' in страница


def test_без_почты_так_и_сказано(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings").get_data(as_text=True)

        assert "Почта Google не привязана" in страница and 'name="current"' in страница


def test_тексты_есть_по_английски(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ", ui_lang="en").test_client() as client:
        войти(client)
        страница = client.get("/settings?lang=en").get_data(as_text=True)

    assert "Settings" in страница and "Telegram bot" in страница
    assert "Interface language" in страница and "Настройки" not in страница
