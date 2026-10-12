"""Свежий вход перед долгоживущим доступом (аудит безопасности 12.10, `web.reauth`).

Украденная сессия не должна выпускать себе токен Claude, привязывать свой
Telegram, привязывать или снимать почту Google: эти права пережили бы выход и
смену пароля. Каждое такое действие при входе старше 15 минут уводит на
«Подтвердите вход» и само не делается. Подтверждение — тем способом, каким
учётка входит, и заменяет сессию свежей. Слой базы подменён на границе.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, ТОКЕН, Сессия, Учётка, войти, подменить_двери, собрать

from src.db import bot_links, web_own_profile
from src.web import auth, reauth, users_mcp
from src.web.google_auth import GoogleIdentity, GoogleSettings

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ПОЧТА = "director@dodobrands.io"
НОВЫЙ_ТОКЕН = "свежая-сессия"
РЕКВИЗИТЫ = GoogleSettings("c", "s", "https://стенд.example/auth/google/callback")

#: (путь, данные, якорь возврата, дверь, которую НЕ должны позвать)
ДЕЙСТВИЯ = [
    ("/settings/claude-token", {}, "#claude-token", "issue"),
    ("/settings/bot-link", {}, "#bot", "link"),
    ("/settings/google-link", {}, "#google", "begin"),
]


class Двери:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.звали: list[str] = []
        self.открыто: list[str] = []
        self.закрыто: list[str] = []

        def _issue(*_: Any, **__: Any) -> Any:
            self.звали.append("issue")
            raise AssertionError("токен выпущен по несвежей сессии")

        def _link(*_: Any, **__: Any) -> Any:
            self.звали.append("link")
            raise AssertionError("ссылка бота выпущена по несвежей сессии")

        def _begin(*_: Any, **__: Any) -> bool:
            self.звали.append("begin")
            return True

        def _unlink(*_: Any, **__: Any) -> str:
            self.звали.append("unlink")
            return "ok"

        monkeypatch.setattr(users_mcp, "issue_own", _issue)
        monkeypatch.setattr(bot_links, "issue_link", _link)
        monkeypatch.setattr(web_own_profile, "begin_google_link", _begin)
        monkeypatch.setattr(web_own_profile, "unlink_google", _unlink)


def _стенд(
    monkeypatch: pytest.MonkeyPatch,
    *,
    минут: int,
    email: str | None = None,
    google: bool = True,
) -> Iterator[tuple[FlaskClient, Двери]]:
    двери = Двери(monkeypatch)
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    if google:
        monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    with собрать(tenant="HQ", bot_username="decimus_demo_bot").test_client() as client:
        assert войти(client).status_code == 302
        когда = datetime.now(UTC) - timedelta(minutes=минут)

        def _resolve(token: str) -> Учётка | None:
            if token == ТОКЕН:
                return Учётка(tenant="HQ", role="admin", email=email, signed_in_at=когда)
            if token == НОВЫЙ_ТОКЕН:
                return Учётка(tenant="HQ", role="admin", email=email)
            return None

        monkeypatch.setattr(auth, "resolve_session", _resolve)

        def _open(account: Учётка) -> Сессия:
            двери.открыто.append(account.login)
            return Сессия(НОВЫЙ_ТОКЕН)

        def _close(token: str) -> bool:
            двери.закрыто.append(token)
            return True

        monkeypatch.setattr(auth, "open_session", _open)
        monkeypatch.setattr(auth, "close_session", _close)
        yield client, двери


def _на_подтверждение(ответ: Any) -> str:
    assert ответ.status_code == 302, ответ.status_code
    адрес = urlsplit(ответ.headers["Location"])
    assert адрес.path == reauth.CONFIRM_PATH, ответ.headers["Location"]
    return parse_qs(адрес.query)["next"][0]


@pytest.mark.parametrize(("путь", "данные", "якорь", "дверь"), ДЕЙСТВИЯ)
def test_несвежий_вход_переспрашивает_и_не_делает(
    monkeypatch: pytest.MonkeyPatch, путь: str, данные: dict[str, str], якорь: str, дверь: str
) -> None:
    for client, двери in _стенд(monkeypatch, минут=16):
        назад = _на_подтверждение(client.post(путь, data=данные, headers=ЗАГОЛОВКИ))

        assert назад == f"/settings{якорь}"
        assert дверь not in двери.звали


def test_несвежий_вход_почту_google_не_снимает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=16, email=ПОЧТА):
        ответ = client.post(
            "/settings/google-unlink", data={"current": "верный-пароль"}, headers=ЗАГОЛОВКИ
        )

        assert _на_подтверждение(ответ) == "/settings#google"
        assert "unlink" not in двери.звали


def test_свежий_вход_действие_делает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=14):
        ответ = client.post("/settings/google-link", headers=ЗАГОЛОВКИ)

        assert ответ.headers["Location"].startswith("https://accounts.google.com/")
        assert двери.звали == ["begin"]


def test_снять_доступ_можно_и_по_несвежему_входу(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отзыв уменьшает доступ — переспрашивать незачем."""
    monkeypatch.setattr(bot_links, "unbind", lambda _user_id: True)
    for client, _ in _стенд(monkeypatch, минут=60):
        ответ = client.post("/settings/bot-unlink", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 200


# ── Подтверждение паролем ──────────────────────────────────────────────


def test_пароль_не_тот_сессию_не_меняет(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=16, google=False):
        ответ = client.post(
            reauth.CONFIRM_PATH,
            data={"password": "не-тот", "next": "/settings#bot"},
            headers=ЗАГОЛОВКИ,
        )

        assert ответ.status_code == 401
        assert двери.открыто == [] and двери.закрыто == []


def test_верный_пароль_меняет_сессию_и_возвращает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=16, google=False):
        страница = client.get(f"{reauth.CONFIRM_PATH}?next=/settings%23bot").get_data(as_text=True)
        assert "Подтвердите вход" in страница and "не старше 15" in страница

        ответ = client.post(
            reauth.CONFIRM_PATH,
            data={"password": "верный-пароль", "next": "/settings#bot"},
            headers=ЗАГОЛОВКИ,
        )

        assert ответ.status_code == 302 and ответ.headers["Location"] == "/settings#bot"
        assert двери.закрыто == [ТОКЕН], "прежняя сессия не закрыта"
        assert двери.открыто == ["director"]
        # Новая кука — свежая сессия: действие проходит.
        assert client.post("/settings/google-link", headers=ЗАГОЛОВКИ).status_code == 302
        assert "begin" not in двери.звали  # реквизитов нет — к Google не уводят


@pytest.mark.parametrize("назад", ["//evil.example", "https://evil.example/settings", "/overview"])
def test_возврат_только_в_настройки_или_согласие(
    monkeypatch: pytest.MonkeyPatch, назад: str
) -> None:
    for client, _ in _стенд(monkeypatch, минут=16, google=False):
        ответ = client.post(
            reauth.CONFIRM_PATH,
            data={"password": "верный-пароль", "next": назад},
            headers=ЗАГОЛОВКИ,
        )

        assert ответ.headers["Location"] == "/settings"


def test_учётка_с_google_паролем_не_подтверждает(monkeypatch: pytest.MonkeyPatch) -> None:
    """D450: с привязанной почтой паролем не входят — и не подтверждают."""
    for client, двери in _стенд(monkeypatch, минут=16, email=ПОЧТА):
        страница = client.get(reauth.CONFIRM_PATH).get_data(as_text=True)
        assert "Подтвердить через Google" in страница and 'name="password"' not in страница

        ответ = client.post(
            reauth.CONFIRM_PATH, data={"password": "верный-пароль"}, headers=ЗАГОЛОВКИ
        )

        assert ответ.status_code == 403 and двери.открыто == []


# ── Подтверждение через Google ─────────────────────────────────────────


def _через_google(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, *, почта: str, домен: str
) -> Any:
    ответ = client.post(
        reauth.CONFIRM_GOOGLE_PATH, data={"next": "/settings#claude-token"}, headers=ЗАГОЛОВКИ
    )
    параметры = parse_qs(urlsplit(ответ.headers["Location"]).query)
    метка, nonce = параметры["state"][0], параметры["nonce"][0]
    monkeypatch.setattr(
        auth,
        "exchange_code",
        lambda settings, *, code: GoogleIdentity(
            email=почта, email_verified=True, hosted_domain=домен, nonce=nonce
        ),
    )
    return client.get(auth.GOOGLE_CALLBACK_PATH, query_string={"state": метка, "code": "код"})


def test_google_другой_почтой_не_подтверждает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=16, email=ПОЧТА):
        ответ = _через_google(
            client, monkeypatch, почта="someone@dodobrands.io", домен="dodobrands.io"
        )

        assert urlsplit(ответ.headers["Location"]).path == reauth.CONFIRM_PATH
        assert "failed=1" in ответ.headers["Location"]
        assert двери.открыто == []


def test_google_личным_аккаунтом_учётку_ук_не_подтверждает(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client, двери in _стенд(monkeypatch, минут=16, email=ПОЧТА):
        ответ = _через_google(client, monkeypatch, почта=ПОЧТА, домен="")

        assert "failed=1" in ответ.headers["Location"] and двери.открыто == []


def test_google_своей_почтой_подтверждает_и_возвращает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=16, email=ПОЧТА):
        ответ = _через_google(client, monkeypatch, почта=ПОЧТА, домен="dodobrands.io")

        assert ответ.headers["Location"] == "/settings#claude-token"
        assert двери.закрыто == [ТОКЕН] and двери.открыто == ["director"]


def test_свежесть_граница_и_неизвестное_время() -> None:
    сейчас = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

    assert reauth.is_fresh(Учётка(signed_in_at=сейчас - reauth.MAX_AGE), now=сейчас)
    assert not reauth.is_fresh(
        Учётка(signed_in_at=сейчас - reauth.MAX_AGE - timedelta(seconds=1)), now=сейчас
    )
    assert not reauth.is_fresh(object(), now=сейчас)
