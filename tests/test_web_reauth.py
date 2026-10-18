"""Свежий вход перед долгоживущим доступом (аудит безопасности 12.10, `web.reauth`).

Украденная сессия не должна выпускать себе токен Claude, привязывать свой
Telegram, привязывать или снимать почту Google: эти права пережили бы выход и
смену пароля. Каждое такое действие при входе старше 12 часов (D457) уводит на
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
#: Минуты со входа: за пределом окна в 12 часов (D457) и внутри него.
ПОСЛЕ_ОКНА = 12 * 60 + 1
ВНУТРИ_ОКНА = 12 * 60 - 1
ПОЧТА = "director@dodobrands.io"
НОВЫЙ_ТОКЕН = "свежая-сессия"
РЕКВИЗИТЫ = GoogleSettings("c", "s", "https://стенд.example/auth/google/callback")

#: (путь, данные, якорь возврата, дверь, которую НЕ должны позвать)
ДЕЙСТВИЯ = [
    ("/settings/claude-token", {}, "?tile=claude", "issue"),
    ("/settings/bot-link", {}, "?tile=bot", "link"),
    ("/settings/google-link", {}, "?tile=google", "begin"),
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

        def _open(account: Учётка, **_: object) -> Сессия:
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
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА):
        назад = _на_подтверждение(client.post(путь, data=данные, headers=ЗАГОЛОВКИ))

        assert назад == f"/settings{якорь}"
        assert дверь not in двери.звали


def test_несвежий_вход_почту_google_не_снимает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        ответ = client.post(
            "/settings/google-unlink", data={"current": "верный-пароль"}, headers=ЗАГОЛОВКИ
        )

        assert _на_подтверждение(ответ) == "/settings?tile=google"
        assert "unlink" not in двери.звали


def test_свежий_вход_действие_делает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=ВНУТРИ_ОКНА):
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
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, google=False):
        ответ = client.post(
            reauth.CONFIRM_PATH,
            data={"password": "не-тот", "next": "/settings#bot"},
            headers=ЗАГОЛОВКИ,
        )

        assert ответ.status_code == 401
        assert двери.открыто == [] and двери.закрыто == []


def test_верный_пароль_меняет_сессию_и_возвращает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, google=False):
        страница = client.get(f"{reauth.CONFIRM_PATH}?next=/settings%23bot").get_data(as_text=True)
        assert "Подтвердите вход" in страница and "не старше 12" in страница

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
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, google=False):
        ответ = client.post(
            reauth.CONFIRM_PATH,
            data={"password": "верный-пароль", "next": назад},
            headers=ЗАГОЛОВКИ,
        )

        assert ответ.headers["Location"] == "/settings"


def test_учётка_с_google_паролем_не_подтверждает(monkeypatch: pytest.MonkeyPatch) -> None:
    """D450: с привязанной почтой паролем не входят — и не подтверждают."""
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
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
            email=почта,
            email_verified=True,
            hosted_domain=домен,
            nonce=nonce,
            subject="110169484474386276334",
        ),
    )
    return client.get(auth.GOOGLE_CALLBACK_PATH, query_string={"state": метка, "code": "код"})


def test_google_другой_почтой_не_подтверждает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        ответ = _через_google(
            client, monkeypatch, почта="someone@dodobrands.io", домен="dodobrands.io"
        )

        assert urlsplit(ответ.headers["Location"]).path == reauth.CONFIRM_PATH
        assert "failed=1" in ответ.headers["Location"]
        assert двери.открыто == []


def test_google_личным_аккаунтом_учётку_ук_не_подтверждает(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        ответ = _через_google(client, monkeypatch, почта=ПОЧТА, домен="")

        assert "failed=1" in ответ.headers["Location"] and двери.открыто == []


def test_google_своей_почтой_подтверждает_и_возвращает(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
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


def test_окно_свежести_двенадцать_часов() -> None:
    """D457: ровно 12 часов; прежние 15 минут вернули бы переспрос активному человеку."""
    assert reauth.MAX_AGE == timedelta(hours=12)


# ── Действие выполняется само после подтверждения (D457) ───────────────


class Выпуски:
    """Считает, сколько раз реально выпустили токен: «один раз» — это число, не вид."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.число = 0

        def _issue(*_: Any, **__: Any) -> users_mcp.Issued:
            self.число += 1
            return users_mcp.Issued(command="claude mcp add СЕКРЕТНАЯ-КОМАНДА")

        monkeypatch.setattr(users_mcp, "issue_own", _issue)


def _подтвердить_паролем(client: FlaskClient) -> Any:
    return client.post(
        reauth.CONFIRM_PATH,
        data={"password": "верный-пароль", "next": "/settings#claude-token"},
        headers=ЗАГОЛОВКИ,
    )


def _заряжено_через_google(client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подтверждение через Google заряжает намерение, но само его не выполняет."""
    _через_google(client, monkeypatch, почта=ПОЧТА, домен="dodobrands.io")


def test_после_подтверждения_паролем_токен_выпускается_сразу_и_один_раз(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, google=False):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        assert выпуски.число == 0

        страница = _подтвердить_паролем(client)

        assert выпуски.число == 1
        assert "СЕКРЕТНАЯ-КОМАНДА" in страница.get_data(as_text=True)
        assert страница.headers["Cache-Control"] == "no-store"
        # Новая сессия приехала в этом же ответе.
        assert any(
            кука.startswith(auth.COOKIE_NAME) for кука in страница.headers.getlist("Set-Cookie")
        )
        # Повтор подтверждения: намерение снято тем же ответом — второго выпуска нет.
        повтор = _подтвердить_паролем(client)
        assert выпуски.число == 1
        assert "СЕКРЕТНАЯ-КОМАНДА" not in повтор.get_data(as_text=True)


def test_после_подтверждения_через_google_токен_выпускается_кнопкой_и_один_раз(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        _заряжено_через_google(client, monkeypatch)
        # GET — чистое чтение: заряженное намерение здесь ничего не выпускает.
        assert "СЕКРЕТНАЯ-КОМАНДА" not in client.get("/settings").get_data(as_text=True)
        assert выпуски.число == 0

        страница = client.post("/settings/continue", headers=ЗАГОЛОВКИ)

        assert выпуски.число == 1
        assert "СЕКРЕТНАЯ-КОМАНДА" in страница.get_data(as_text=True)
        assert страница.headers["Cache-Control"] == "no-store"
        повтор = client.post("/settings/continue", headers=ЗАГОЛОВКИ)
        assert выпуски.число == 1
        assert "СЕКРЕТНАЯ-КОМАНДА" not in повтор.get_data(as_text=True)


def test_get_настроек_с_заряженным_намерением_ничего_не_выпускает(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        _заряжено_через_google(client, monkeypatch)

        for _ in range(3):
            client.get("/settings")

        assert выпуски.число == 0


def test_продолжить_чужой_страницей_не_выполняется(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        _заряжено_через_google(client, monkeypatch)

        ответ = client.post("/settings/continue", headers={"Origin": "https://evil.example"})

        assert ответ.status_code == 403
        assert выпуски.число == 0


def test_после_подтверждения_через_google_действие_тоже_выполняется(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))

        _через_google(client, monkeypatch, почта=ПОЧТА, домен="dodobrands.io")
        client.post("/settings/continue", headers=ЗАГОЛОВКИ)

        assert выпуски.число == 1


def test_намерение_без_подтверждения_не_выполняется(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отказ по свежести кладёт намерение, но «заряжает» его только подтверждение."""
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, google=False):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        # Вход обычным путём (не подтверждением): сессия свежая, а намерение не заряжено.
        monkeypatch.setattr(
            auth, "resolve_session", lambda token: Учётка(tenant="HQ", role="admin")
        )

        client.post("/settings/continue", headers=ЗАГОЛОВКИ)

        assert выпуски.число == 0


def test_подделанное_и_чужое_намерение_не_выполняется(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        _заряжено_через_google(client, monkeypatch)
        app = client.application
        подпись = app.extensions[reauth.INTENT_SIGNER_KEY]

        for кука in (
            "подделка",
            подпись.dumps({"a": "claude-token", "u": "другая-учётка", "armed": True}),
            подпись.dumps({"a": "снять-всё", "u": Учётка().id, "armed": True}),
        ):
            client.set_cookie(reauth.INTENT_COOKIE, кука)
            client.post("/settings/continue", headers=ЗАГОЛОВКИ)

        assert выпуски.число == 0


def test_снятие_почты_само_не_выполняется(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пароль для снятия лежит в форме, а форму не храним: человек нажимает ещё раз."""
    for client, двери in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА, google=False):
        ответ = client.post(
            "/settings/google-unlink", data={"current": "верный-пароль"}, headers=ЗАГОЛОВКИ
        )
        _на_подтверждение(ответ)
        _подтвердить_паролем(client)

        client.post("/settings/continue", headers=ЗАГОЛОВКИ)

        assert "unlink" not in двери.звали


def test_намерение_не_переживает_срок(monkeypatch: pytest.MonkeyPatch) -> None:
    for client, _ in _стенд(monkeypatch, минут=ПОСЛЕ_ОКНА, email=ПОЧТА):
        выпуски = Выпуски(monkeypatch)
        _на_подтверждение(client.post("/settings/claude-token", headers=ЗАГОЛОВКИ))
        _заряжено_через_google(client, monkeypatch)
        monkeypatch.setattr(reauth, "INTENT_TTL_SECONDS", -1)

        client.post("/settings/continue", headers=ЗАГОЛОВКИ)

        assert выпуски.число == 0
