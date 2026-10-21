"""Экран «Настройки» (D447): один набор своего профиля для любой роли.

Права — ядро: «Настройки» открыты каждому вошедшему, но дела в них — только
СВОИ, а гость на запись не допущен нигде, кроме пароля и своего Claude. Слой
базы подменён на границе, как в соседних наборах.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.web import auth, users_mcp
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

РАЗДЕЛЫ = ('id="connections"',)

#: Все плитки страницы (D470, вся страница плитками): у каждой своя панель, `id` панели = ключ.
ПЛИТКИ = (
    "profile",
    "language",
    "password",
    "security",
    "signins",
    "signout",
    "claude",
    "bot",
    "google",
)


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
        # Плитки (D470): каждая плитка — свой выбор в адресе, панель — выбранная.
        for плитка in ПЛИТКИ:
            панель = client.get(f"/settings?tile={плитка}")
            assert f'id="{плитка}"' in панель.get_data(as_text=True), (tenant, role, плитка)
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

    assert ответ.status_code == 302 and "/welcome?next=" in ответ.headers["Location"]


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
    for client in _стенд(monkeypatch, tenant="HQ", role="developer"):
        страница = client.get("/settings?tile=bot").get_data(as_text=True)

        assert "WEB_BOT_USERNAME" in страница and "/settings/bot-link" not in страница


def test_адрес_mcp_берётся_из_настройки_стенда(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(
        monkeypatch,
        tenant="HQ",
        role="auditor",
        admin_public_url="https://admin.example",
        mcp_public_url="https://mcp.example/mcp",
    ):
        страница = client.get("/settings?tile=claude").get_data(as_text=True)

        assert "https://mcp.example/mcp" in страница


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
        страница = client.get("/settings?tile=password").get_data(as_text=True)

        assert 'id="password-form"' not in страница, "форма смены пароля при закрытом входе паролем"
        assert "Вход паролем для этой учётки закрыт" in страница


def test_с_почтой_без_google_пароль_остаётся(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _с_почтой(monkeypatch, google=False):
        страница = client.get("/settings?tile=password").get_data(as_text=True)

        assert 'id="password-form"' in страница
        assert ПОЧТА in client.get("/settings").get_data(as_text=True)


def test_без_почты_так_и_сказано(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings?tile=google").get_data(as_text=True)
        пароль = client.get("/settings?tile=password").get_data(as_text=True)

        assert "Почта Google не привязана" in страница and 'name="current"' in пароль


def test_тексты_есть_по_английски(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ", ui_lang="en").test_client() as client:
        войти(client)
        страница = client.get("/settings?lang=en").get_data(as_text=True)

    assert "Settings" in страница and "Telegram bot" in страница
    assert "Interface language" in страница and "Настройки" not in страница


# --- «Выйти везде» (D462) ----------------------------------------------------------


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_выйти_везде_закрывает_свою_сессию_и_уводит_на_вход(
    monkeypatch: pytest.MonkeyPatch, tenant: str, role: str
) -> None:
    from src.web import accounts

    закрытые: list[str] = []
    monkeypatch.setattr(
        accounts, "sign_out_everywhere", lambda token: закрытые.append(token) or True
    )

    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.post("/settings/sign-out-everywhere", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 302 and ответ.headers["Location"].endswith("/login"), role
        assert закрытые == [ТОКЕН], "закрыта не та сессия: чья учётка — решает сессия, не форма"
        assert f"{auth.COOKIE_NAME}=;" in ответ.headers.get("Set-Cookie", ""), "кука осталась"


def test_выйти_везде_берёт_учётку_из_сессии_а_не_из_формы(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.web import accounts

    закрытые: list[str] = []
    monkeypatch.setattr(
        accounts, "sign_out_everywhere", lambda token: закрытые.append(token) or True
    )

    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        client.post(
            "/settings/sign-out-everywhere",
            data={"user_id": "чужая-учётка", "token": "чужой-токен", "login": "boss2"},
            headers=ЗАГОЛОВКИ,
        )

    assert закрытые == [ТОКЕН]


def test_выйти_везде_с_чужой_страницы_не_закрывает_ничего(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.web import accounts

    закрытые: list[str] = []
    monkeypatch.setattr(
        accounts, "sign_out_everywhere", lambda token: закрытые.append(token) or True
    )

    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        ответ = client.post(
            "/settings/sign-out-everywhere", headers={"Origin": "https://evil.example"}
        )

        assert ответ.status_code == 403
    assert закрытые == []


def test_выйти_везде_при_отказе_базы_не_выходит_молча(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.db.errors import AccessError
    from src.web import accounts

    def отказ(token: str) -> bool:
        raise AccessError("база не ответила")

    monkeypatch.setattr(accounts, "sign_out_everywhere", отказ)

    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        ответ = client.post("/settings/sign-out-everywhere", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 503
        assert "Не закрыто" in ответ.get_data(as_text=True)
        assert (
            "Set-Cookie" not in ответ.headers
            or auth.COOKIE_NAME + "=;" not in ответ.headers["Set-Cookie"]
        ), "кука стёрта, а сессия в базе жива"


def test_выбранная_плитка_берётся_из_адреса_а_без_него_первая(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin", bot_username="decimus_bot"):
        по_умолчанию = client.get("/settings").get_data(as_text=True)
        бот = client.get("/settings?tile=bot").get_data(as_text=True)
        чужое = client.get("/settings?tile=../x").get_data(as_text=True)

        # Первая — Claude: секция «Подключения» идёт первой (D589).
        assert 'id="claude"' in по_умолчанию and 'id="bot"' not in по_умолчанию
        assert 'id="bot"' in бот and 'id="claude"' not in бот
        assert бот.count('aria-current="true"') == 1, "выбрана должна быть ровно одна плитка"
        assert 'id="claude"' in чужое, "неизвестная плитка не должна ломать страницу"


def test_плитки_показывают_статус_и_счётчик(monkeypatch: pytest.MonkeyPatch) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin", bot_username="decimus_bot"):
        страница = client.get("/settings").get_data(as_text=True)

        assert страница.count('<a class="stile') == len(ПЛИТКИ), "не все плитки на месте"
        assert "Не подключено" in страница


def test_каждая_плитка_со_своей_панелью_и_своим_статусом(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вся страница плитками: одинаковые плитки, у каждой своя панель, длинное — не на плитке."""
    for client in _стенд(monkeypatch, tenant="HQ", role="admin", bot_username="decimus_bot"):
        for плитка in ПЛИТКИ:
            страница = client.get(f"/settings?tile={плитка}").get_data(as_text=True)

            assert f"&tile={плитка}#connections" in страница, f"плитки {плитка} нет"
            assert страница.count('class="ssec"') == 1, f"панель {плитка}: не одна"
            assert f'<div class="ssec" id="{плитка}">' in страница, f"нет панели {плитка}"
        # Профиль, язык и пароль больше не отдельные карточки страницы.
        страница = client.get("/settings").get_data(as_text=True)
        assert "scard--profile" not in страница and 'class="scard" id="language"' not in страница


def test_исход_действия_раскрывает_свою_плитку() -> None:
    from src.web import settings_screen as экран

    assert (
        экран.selected_tile(
            экран.Show(flash=экран.Flash("settings.google.unlink.wrong", ok=False)), None
        )
        == "google"
    )
    assert (
        экран.selected_tile(экран.Show(flash=экран.Flash("users.bot.unlinked", ok=True)), None)
        == "bot"
    )
    assert (
        экран.selected_tile(экран.Show(flash=экран.Flash("users.mcp.revoked", ok=True)), None)
        == "claude"
    )
    assert экран.selected_tile(экран.Show(), "bot") == "bot"
    assert экран.selected_tile(экран.Show(), "security") == "security"
    assert (
        экран.selected_tile(
            экран.Show(flash=экран.Flash("settings.signout.failed", ok=False)), None
        )
        == "signout"
    )


def test_плитка_claude_как_в_swarm_кнопка_инструкции_без_подразделов(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D476: «Получить команду установки», «Инструкции для проекта» с готовым текстом,
    без подразделов Claude Desktop / Claude Code."""
    monkeypatch.setattr(users_mcp, "own_status", lambda _id: users_mcp.TokenStatus(known=True))
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings?tile=claude").get_data(as_text=True)

        assert "Получить команду установки" in страница
        assert "Инструкции для проекта" in страница
        assert "decimus" in страница and "get_inspection" in страница, "текст инструкции"
        assert 'class="ssec__sub"' not in страница, "подразделы Claude Desktop / Claude Code убраны"
        assert "Claude Desktop" not in страница

        по_английски = client.get("/settings?tile=claude&lang=en").get_data(as_text=True)
        assert "Get the install command" in по_английски
        assert "Never compute a score yourself" in по_английски


def test_в_левой_колонке_группы_разделены_чертами(monkeypatch: pytest.MonkeyPatch) -> None:
    """D478: рабочая, вспомогательная, техническая — две черты между тремя группами."""
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings").get_data(as_text=True)
        список = страница[страница.index('class="sidenav__list"') :]
        список = список[: список.index('class="sidenav__foot"')]

        assert список.count('class="sidenav__sep"') == 2


def test_перевыпуск_команды_claude_идёт_через_подтверждение(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Токен уже есть: вместо «Получить» — «Перевыпустить» за подтверждением (гасит прежний)."""
    monkeypatch.setattr(
        users_mcp,
        "own_status",
        lambda _id: users_mcp.TokenStatus(known=True, expires_at=datetime(2027, 1, 1)),
    )
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings?tile=claude").get_data(as_text=True)

        assert "Перевыпустить команду установки" in страница
        assert "Получить команду установки" not in страница
        assert 'class="sconfirm"' in страница
