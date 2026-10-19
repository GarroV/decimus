"""Сервер авторизации OAuth веб-админки (D417) — уровень страниц, без базы.

Ядро: ошибка здесь тихая — код уходит на чужой адрес, обмен проходит без
PKCE, повторный код или украденный refresh работают, после входа человека
уводит на чужой сайт. Хранилище подменено в памяти (`oauth_harness`), правила
обмена и адреса возврата — продуктовые.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from flask.testing import FlaskClient
from oauth_harness import ПамятьOAuth, подменить_oauth
from web_harness import СВОЙ, войти, подменить_двери, подменить_счётчики, собрать

from src.web import auth, oauth

ТЕНАНТ = "HQ"
АДМИНКА = "https://admin.example"
MCP = "https://mcp.example/mcp"
ВОЗВРАТ = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "verifier-" + "z" * 50
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


@pytest.fixture
def память(monkeypatch: pytest.MonkeyPatch) -> ПамятьOAuth:
    подменить_счётчики(monkeypatch)
    return подменить_oauth(monkeypatch)


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    приложение = собрать(tenant=ТЕНАНТ, admin_public_url=АДМИНКА, mcp_public_url=MCP)
    with приложение.test_client() as client:
        yield client


def _регистрация(client: FlaskClient, *адреса: str) -> Any:
    return client.post(
        oauth.REGISTER_PATH, json={"client_name": "Claude", "redirect_uris": list(адреса)}
    )


def _клиент_claude(client: FlaskClient) -> str:
    ответ = _регистрация(client, ВОЗВРАТ)
    assert ответ.status_code == 201
    return str(ответ.get_json()["client_id"])


def _параметры(client_id: str, **иное: str) -> dict[str, str]:
    параметры = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": ВОЗВРАТ,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "состояние-клиента",
        "scope": "mcp",
        "resource": MCP,
    }
    параметры.update(иное)
    return параметры


def _разрешить(client: FlaskClient, client_id: str, **иное: str) -> Any:
    return client.post(
        oauth.AUTHORIZE_PATH,
        data={**_параметры(client_id, **иное), "decision": "allow"},
        headers={"Origin": СВОЙ},
    )


def _запрос_возврата(ответ: Any) -> dict[str, list[str]]:
    адрес = ответ.headers["Location"]
    assert адрес.startswith(ВОЗВРАТ + "?"), адрес
    return parse_qs(urlsplit(адрес).query)


def _код(client: FlaskClient, client_id: str) -> str:
    войти(client)
    return _запрос_возврата(_разрешить(client, client_id))["code"][0]


def _обмен(client: FlaskClient, client_id: str, код: str, **иное: str) -> Any:
    данные = {
        "grant_type": "authorization_code",
        "code": код,
        "client_id": client_id,
        "redirect_uri": ВОЗВРАТ,
        "code_verifier": VERIFIER,
    }
    данные.update(иное)
    return client.post(oauth.TOKEN_PATH, data=данные)


# --- включение и метаданные -------------------------------------------------


def test_без_публичных_адресов_oauth_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert client.get("/.well-known/oauth-authorization-server").status_code != 200
        assert client.post(oauth.TOKEN_PATH).status_code != 200


def test_метаданные_называют_внешние_адреса(клиент: FlaskClient) -> None:
    данные = клиент.get("/.well-known/oauth-authorization-server").get_json()

    assert данные["issuer"] == АДМИНКА
    assert данные["authorization_endpoint"] == f"{АДМИНКА}{oauth.AUTHORIZE_PATH}"
    assert данные["token_endpoint"] == f"{АДМИНКА}{oauth.TOKEN_PATH}"
    assert данные["registration_endpoint"] == f"{АДМИНКА}{oauth.REGISTER_PATH}"
    assert данные["code_challenge_methods_supported"] == ["S256"]
    assert данные["token_endpoint_auth_methods_supported"] == ["none"]


# --- регистрация: только адреса Claude ---------------------------------------


@pytest.mark.parametrize(
    "адрес",
    [
        ВОЗВРАТ,
        "https://claude.com/api/mcp/auth_callback",
        "http://localhost:51234/callback",
        "http://127.0.0.1:8080/callback",
    ],
)
def test_регистрация_адреса_claude(клиент: FlaskClient, адрес: str) -> None:
    ответ = _регистрация(клиент, адрес)

    assert ответ.status_code == 201
    assert ответ.get_json()["token_endpoint_auth_method"] == "none"


@pytest.mark.parametrize(
    "адрес", ["https://evil.com/cb", "http://localhost.evil.com/callback", "javascript:alert(1)"]
)
def test_регистрация_чужого_адреса_отвергается(
    клиент: FlaskClient, память: ПамятьOAuth, адрес: str
) -> None:
    ответ = _регистрация(клиент, ВОЗВРАТ, адрес)

    assert ответ.status_code == 400
    assert ответ.get_json()["error"] == "invalid_redirect_uri"
    assert not память.clients


def _регистрация_с(client: FlaskClient, адрес: str) -> Any:
    return client.post(
        oauth.REGISTER_PATH,
        json={"client_name": "Claude", "redirect_uris": [ВОЗВРАТ]},
        environ_base={"REMOTE_ADDR": адрес},
    )


def test_предел_регистраций_на_адрес(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    """Перебирающий с одного адреса упирается в свой предел, а не выбирает общий за всех."""
    for _ in range(oauth.REGISTRATIONS_PER_ADDRESS):
        assert _регистрация_с(клиент, "198.51.100.7").status_code == 201

    лишняя = _регистрация_с(клиент, "198.51.100.7")
    сосед = _регистрация_с(клиент, "198.51.100.8")

    assert лишняя.status_code == 429
    assert лишняя.headers["Retry-After"] == str(int(oauth.REGISTRATION_WINDOW.total_seconds()))
    assert len(память.clients) == oauth.REGISTRATIONS_PER_ADDRESS + 1
    assert сосед.status_code == 201


@pytest.mark.parametrize(
    ("прокси", "заголовки"),
    [
        # Без доверенных прокси заголовки не читаются вовсе.
        (0, {"X-Forwarded-For": "{подставной}"}),
        (0, {"CF-Connecting-IP": "{подставной}", "X-Real-IP": "{подставной}"}),
        # Один доверенный прокси: берётся звено, дописанное им, — крайнее справа;
        # звенья левее клиент дописывает сам, и они не в счёт.
        (1, {"X-Forwarded-For": "{подставной}, 198.51.100.7"}),
    ],
)
def test_подставной_заголовок_не_даёт_нового_адреса(
    monkeypatch: pytest.MonkeyPatch,
    память: ПамятьOAuth,
    прокси: int,
    заголовки: dict[str, str],
) -> None:
    """Адрес — как у входа и `swarm_api`: `remote.client_address` и `trusted_proxies`."""
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    приложение = собрать(
        tenant=ТЕНАНТ, admin_public_url=АДМИНКА, mcp_public_url=MCP, trusted_proxies=прокси
    )
    with приложение.test_client() as клиент:

        def регистрация(номер: int) -> int:
            подставные = {
                имя: значение.format(подставной=f"203.0.113.{номер}")
                for имя, значение in заголовки.items()
            }
            return клиент.post(
                oauth.REGISTER_PATH,
                json={"client_name": "Claude", "redirect_uris": [ВОЗВРАТ]},
                headers=подставные,
                environ_base={"REMOTE_ADDR": "198.51.100.7"},
            ).status_code

        коды = [регистрация(номер) for номер in range(oauth.REGISTRATIONS_PER_ADDRESS + 1)]

    assert коды[:-1] == [201] * oauth.REGISTRATIONS_PER_ADDRESS
    assert коды[-1] == 429
    assert {откуда for откуда, _ in память.registered.values()} == {"198.51.100.7"}


def test_общий_предел_регистраций(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    сейчас = datetime.now(UTC)
    for номер in range(oauth.REGISTRATIONS_PER_WINDOW):
        память.registered[f"c{номер}"] = (f"адрес-{номер}", сейчас)

    ответ = _регистрация_с(клиент, "198.51.100.9")

    assert ответ.status_code == 429
    assert oauth.REGISTRATIONS_PER_ADDRESS < oauth.REGISTRATIONS_PER_WINDOW


def test_чистка_на_регистрации_и_на_выдаче(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    client_id = _клиент_claude(клиент)
    после_регистрации = память.purges

    _обмен(клиент, client_id, _код(клиент, client_id))

    assert после_регистрации == 1
    assert память.purges == 2


# --- согласие ----------------------------------------------------------------


def test_неопознанного_уводит_на_вход_и_обратно(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    ответ = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id))

    assert ответ.status_code == 302
    вход = urlsplit(ответ.headers["Location"])
    assert вход.path == auth.LOGIN_PATH
    вернуться = parse_qs(вход.query)["next"][0]
    assert вернуться.startswith(f"{oauth.AUTHORIZE_PATH}?")

    страница = клиент.get(f"{auth.LOGIN_PATH}?{вход.query}").get_data(as_text=True)
    assert 'name="next"' in страница

    после = клиент.post(
        auth.LOGIN_PATH,
        data={"login": "director", "password": "верный-пароль", "next": вернуться},
        headers={"Origin": СВОЙ},
    )
    assert после.status_code == 302
    assert urlsplit(после.headers["Location"]).path == oauth.AUTHORIZE_PATH


@pytest.mark.parametrize(
    "чужой",
    [
        "https://evil.com/oauth/authorize?x=1",
        "//evil.com/oauth/authorize?x=1",
        "/\\evil.com/oauth/authorize?x=1",
        "/oauth/authorize/../../evil?x=1",
        "javascript:alert(1)",
        "",
    ],
)
def test_next_не_уводит_с_сайта(клиент: FlaskClient, чужой: str) -> None:
    assert auth.safe_next(чужой) is None

    после = клиент.post(
        auth.LOGIN_PATH,
        data={"login": "director", "password": "верный-пароль", "next": чужой},
        headers={"Origin": СВОЙ},
    )

    куда = urlsplit(после.headers["Location"])
    assert куда.netloc in ("", "localhost")
    assert куда.path == "/"


def test_согласие_показывает_клиента_и_хост(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)

    ответ = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id))

    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 200
    assert "Claude" in страница and "claude.ai" in страница
    assert "https://claude.ai" in ответ.headers["Content-Security-Policy"]


@pytest.mark.parametrize(
    ("язык", "предупреждение", "непроверено"),
    [
        ("ru", "только если подключение начали вы сами и только что", "его никто не проверял"),
        (
            "en",
            "Allow only if you started this connection yourself just now",
            "nobody has verified",
        ),
    ],
)
def test_согласие_всегда_предупреждает_и_не_ручается_за_имя(
    monkeypatch: pytest.MonkeyPatch,
    память: ПамятьOAuth,
    язык: str,
    предупреждение: str,
    непроверено: str,
) -> None:
    """Не только для петли: ссылку на согласие с адресом claude.ai может прислать и чужой."""
    подменить_двери(monkeypatch, tenant=ТЕНАНТ)
    приложение = собрать(tenant=ТЕНАНТ, admin_public_url=АДМИНКА, mcp_public_url=MCP, ui_lang=язык)
    with приложение.test_client() as клиент:
        client_id = _клиент_claude(клиент)
        войти(клиент)

        страница = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id)).get_data(
            as_text=True
        )

    assert предупреждение in страница
    assert непроверено in страница


def test_согласие_для_петли_предупреждает(клиент: FlaskClient) -> None:
    петля = "http://localhost:4000/callback"
    client_id = _регистрация(клиент, петля).get_json()["client_id"]
    войти(клиент)

    страница = клиент.get(
        oauth.AUTHORIZE_PATH, query_string=_параметры(client_id, redirect_uri=петля)
    ).get_data(as_text=True)

    assert "Claude Code" in страница


def test_незнакомый_клиент_отказ_без_редиректа(клиент: FlaskClient) -> None:
    войти(клиент)

    ответ = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры("нет-такого"))

    assert ответ.status_code == 400
    assert "Location" not in ответ.headers


@pytest.mark.parametrize(
    "адрес",
    ["https://evil.com/cb", "http://localhost.evil.com/callback", "http://localhost:1/callback"],
)
def test_чужой_адрес_возврата_отказ_без_редиректа(клиент: FlaskClient, адрес: str) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)

    ответ = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id, redirect_uri=адрес))

    assert ответ.status_code == 400
    assert "Location" not in ответ.headers


@pytest.mark.parametrize(
    ("иное", "ошибка"),
    [
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"code_challenge_method": ""}, "invalid_request"),
        ({"code_challenge": "короткий"}, "invalid_request"),
        ({"response_type": "token"}, "unsupported_response_type"),
        ({"resource": "https://other.example/mcp"}, "invalid_target"),
    ],
)
def test_кривой_запрос_возвращается_ошибкой(
    клиент: FlaskClient, иное: dict[str, str], ошибка: str
) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)

    ответ = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id, **иное))

    запрос = _запрос_возврата(ответ)
    assert запрос["error"] == [ошибка]
    assert запрос["state"] == ["состояние-клиента"]
    assert "code" not in запрос


def test_разрешение_без_origin_отвергается(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)

    ответ = клиент.post(oauth.AUTHORIZE_PATH, data={**_параметры(client_id), "decision": "allow"})

    assert ответ.status_code == 403
    assert not память.codes


def test_отказ_человека_возвращает_access_denied(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)

    ответ = клиент.post(
        oauth.AUTHORIZE_PATH,
        data={**_параметры(client_id), "decision": "deny"},
        headers={"Origin": СВОЙ},
    )

    assert _запрос_возврата(ответ)["error"] == ["access_denied"]


# --- обмен кода --------------------------------------------------------------


def test_разрешение_и_обмен_выдают_токены(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)
    запрос = _запрос_возврата(_разрешить(клиент, client_id))
    assert запрос["state"] == ["состояние-клиента"]
    assert запрос["iss"] == [АДМИНКА]

    ответ = _обмен(клиент, client_id, запрос["code"][0])

    данные = ответ.get_json()
    assert ответ.status_code == 200
    assert данные["token_type"] == "Bearer"
    assert данные["access_token"] and данные["refresh_token"]
    assert ответ.headers["Cache-Control"] == "no-store"


def test_код_без_resource_привязан_к_адресу_mcp(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    """RFC 8707: клиент ресурс не назвал — токен всё равно только для своего MCP."""
    client_id = _клиент_claude(клиент)
    войти(клиент)
    параметры = {к: з for к, з in _параметры(client_id).items() if к != "resource"}
    ответ = клиент.post(
        oauth.AUTHORIZE_PATH, data={**параметры, "decision": "allow"}, headers={"Origin": СВОЙ}
    )

    данные = _обмен(клиент, client_id, _запрос_возврата(ответ)["code"][0]).get_json()

    assert память.resolve_access_token(данные["access_token"], resource=MCP) is not None
    assert (
        память.resolve_access_token(данные["access_token"], resource="https://other.example/mcp")
        is None
    )


def test_обмен_с_чужим_resource_отвергается(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)

    ответ = _обмен(клиент, client_id, _код(клиент, client_id), resource="https://other.example/mcp")

    assert ответ.status_code == 400
    assert ответ.get_json()["error"] == "invalid_target"


def test_неверный_verifier_отвергается(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    код = _код(клиент, client_id)

    ответ = _обмен(клиент, client_id, код, code_verifier="другой-" + "q" * 50)

    assert ответ.status_code == 400
    assert ответ.get_json()["error"] == "invalid_grant"


def test_plain_verifier_отвергается(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    код = _код(клиент, client_id)

    ответ = _обмен(клиент, client_id, код, code_verifier=CHALLENGE)

    assert ответ.get_json()["error"] == "invalid_grant"


def test_код_одноразовый_повтор_отзывает_подключение(
    клиент: FlaskClient, память: ПамятьOAuth
) -> None:
    client_id = _клиент_claude(клиент)
    код = _код(клиент, client_id)
    первая = _обмен(клиент, client_id, код).get_json()

    повтор = _обмен(клиент, client_id, код)

    assert повтор.get_json()["error"] == "invalid_grant"
    assert память.resolve_access_token(первая["access_token"], resource=MCP) is None


def test_просроченный_код_отвергается(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    from datetime import UTC, datetime, timedelta

    client_id = _клиент_claude(клиент)
    код = _код(клиент, client_id)
    память.codes[код].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    ответ = _обмен(клиент, client_id, код)

    assert ответ.get_json()["error"] == "invalid_grant"


def test_незнакомый_клиент_на_обмене(клиент: FlaskClient) -> None:
    ответ = _обмен(клиент, "нет-такого", "код")

    assert ответ.status_code == 401
    assert ответ.get_json()["error"] == "invalid_client"


def test_незнакомый_вид_обмена(клиент: FlaskClient) -> None:
    ответ = клиент.post(oauth.TOKEN_PATH, data={"grant_type": "password"})

    assert ответ.get_json()["error"] == "unsupported_grant_type"


# --- refresh -----------------------------------------------------------------


def _refresh(client: FlaskClient, client_id: str, токен: str) -> Any:
    return client.post(
        oauth.TOKEN_PATH,
        data={"grant_type": "refresh_token", "refresh_token": токен, "client_id": client_id},
    )


def test_refresh_ротируется_и_повтор_отзывает_подключение(
    клиент: FlaskClient, память: ПамятьOAuth
) -> None:
    client_id = _клиент_claude(клиент)
    первая = _обмен(клиент, client_id, _код(клиент, client_id)).get_json()

    вторая = _refresh(клиент, client_id, первая["refresh_token"]).get_json()
    assert вторая["refresh_token"] != первая["refresh_token"]
    assert память.resolve_access_token(вторая["access_token"], resource=MCP) is not None

    повтор = _refresh(клиент, client_id, первая["refresh_token"])

    assert повтор.get_json()["error"] == "invalid_grant"
    assert память.resolve_access_token(вторая["access_token"], resource=MCP) is None
    assert _refresh(клиент, client_id, вторая["refresh_token"]).status_code == 400


def test_отключённая_учётка_не_опознаётся(клиент: FlaskClient, память: ПамятьOAuth) -> None:
    client_id = _клиент_claude(клиент)
    пара = _обмен(клиент, client_id, _код(клиент, client_id)).get_json()

    память.disabled.add("22222222-2222-2222-2222-222222222222")

    assert память.resolve_access_token(пара["access_token"], resource=MCP) is None
    assert _refresh(клиент, client_id, пара["refresh_token"]).status_code == 400


def test_неудачи_обмена_запирают_адрес(клиент: FlaskClient) -> None:
    client_id = _клиент_claude(клиент)
    ответы = [_обмен(клиент, client_id, f"код-{номер}").status_code for номер in range(25)]

    assert 429 in ответы


def test_расширенный_form_action_только_на_согласии(клиент: FlaskClient) -> None:
    assert "claude.ai" not in клиент.get(auth.LOGIN_PATH).headers["Content-Security-Policy"]


@pytest.mark.parametrize("роль", ["control", "superadmin", "admin", "auditor"])
def test_согласие_открыто_любой_роли(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth, роль: str
) -> None:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role=роль)
    приложение = собрать(tenant=ТЕНАНТ, admin_public_url=АДМИНКА, mcp_public_url=MCP)
    with приложение.test_client() as client:
        client_id = _клиент_claude(client)
        войти(client)

        ответ = client.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id))
        разрешение = _разрешить(client, client_id)

    assert ответ.status_code == 200
    assert "code" in _запрос_возврата(разрешение)


def test_согласие_открыто_партнёру(monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth) -> None:
    подменить_двери(monkeypatch, tenant="rs", role="admin")
    приложение = собрать(tenant=ТЕНАНТ, admin_public_url=АДМИНКА, mcp_public_url=MCP)
    with приложение.test_client() as client:
        client_id = _клиент_claude(client)
        войти(client)

        ответ = client.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id))

    assert ответ.status_code == 200


# --- свежий вход перед разрешением (аудит безопасности 12.10, `web.reauth`) ----


def _несвежая_сессия(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сессия открыта давно: украденная кука не должна разрешать Claude доступ."""
    from datetime import timedelta

    from web_harness import ТОКЕН, Учётка

    давно = datetime.now(UTC) - timedelta(hours=12, minutes=1)
    monkeypatch.setattr(
        auth,
        "resolve_session",
        lambda token: Учётка(tenant=ТЕНАНТ, signed_in_at=давно) if token == ТОКЕН else None,
    )


def test_несвежий_вход_согласие_переспрашивает_и_возвращает_сюда(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)
    _несвежая_сессия(monkeypatch)

    ответ = клиент.get(oauth.AUTHORIZE_PATH, query_string=_параметры(client_id))

    assert ответ.status_code == 302
    адрес = urlsplit(ответ.headers["Location"])
    assert адрес.path == "/settings/confirm"
    назад = parse_qs(адрес.query)["next"][0]
    assert назад.startswith(oauth.AUTHORIZE_PATH + "?") and client_id in назад


def test_несвежий_вход_разрешение_кода_не_выдаёт(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    client_id = _клиент_claude(клиент)
    войти(клиент)
    _несвежая_сессия(monkeypatch)

    ответ = _разрешить(клиент, client_id)

    assert ответ.status_code == 302
    assert urlsplit(ответ.headers["Location"]).path == "/settings/confirm"
    assert "decision" not in ответ.headers["Location"]
    assert not память.codes, "код выдан по несвежей сессии"


def test_согласие_без_входа_идёт_сразу_на_форму_а_не_на_посадочную(клиент: FlaskClient) -> None:
    """Подключение Claude — не знакомство с продуктом: сразу вход с возвратом (D465, D544)."""
    ответ = клиент.get(f"{oauth.AUTHORIZE_PATH}?client_id=x")

    assert ответ.status_code == 302
    assert ответ.headers["Location"].startswith(f"{auth.LOGIN_PATH}?next=")
