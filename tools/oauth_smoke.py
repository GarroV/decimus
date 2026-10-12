"""Сквозной прогон подключения Claude входом через сайт (D417) против живого стенда.

Инструмент оператора, не тест: проходит протокол так, как его проходит Claude,
и печатает, что увидел. Отвечает на вопрос «подключится ли человек этой роли и
что он увидит в Claude», на который зелёные тесты без базы не отвечают.

    OAUTH_SMOKE_PASSWORD=<пароль тестовой учётки> python3 tools/oauth_smoke.py \\
        --admin https://<адрес админки> --mcp https://<адрес MCP> --login <логин>

Адреса — те же, что в `ADMIN_PUBLIC_URL` и `MCP_PUBLIC_URL` стенда (можно
задать этими же переменными окружения). Пароль — ТОЛЬКО из окружения
(`OAUTH_SMOKE_PASSWORD`): в аргументах он осел бы в истории команд. Ни пароль,
ни коды, ни токены не печатаются.

Шаги:

1. MCP без токена → 401 с `resource_metadata`; документ ресурса называет админку.
2. Метаданные сервера авторизации.
3. Регистрация клиента (DCR) с адресом возврата на петлю.
4. Вход паролем (POST /login с `Origin`) — кука сессии.
5. Страница согласия → «Разрешить» → код в адресе возврата.
6. Обмен кода (PKCE S256) → access + refresh.
7. MCP `initialize` + `tools/list` с access-токеном → список инструментов и роль.
8. Refresh → новая пара; MCP отвечает новым access.
9. Отзыв подключения со своей карточки → MCP отвечает 401.

Учётку берите тестовую: прогон заводит и отзывает настоящее подключение.
Коды возврата: 0 — прошёл, 1 — шаг провален, 2 — не названы адреса, логин или пароль.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import Message
from typing import Any

PASSWORD_VAR = "OAUTH_SMOKE_PASSWORD"  # noqa: S105 — имя переменной, не значение
ADMIN_VAR = "ADMIN_PUBLIC_URL"
MCP_VAR = "MCP_PUBLIC_URL"

#: Адрес возврата на петлю, как у Claude Code. Слушать его не нужно: прогон
#: не идёт по редиректу, а читает код из заголовка `Location`.
CALLBACK = "http://127.0.0.1:53682/callback"

SESSION_COOKIE = "dodo_audit_session"
TIMEOUT_SEC = 20.0


class SmokeError(Exception):
    """Шаг не прошёл. Текст без секретов — его кладут в переписку."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Редиректы не исполняются: код и путь возврата читаются из `Location`."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


@dataclass
class Reply:
    status: int
    headers: Message
    body: str


@dataclass
class Browser:
    """Кука сессии админки — всё, что прогону нужно от браузера."""

    cookies: dict[str, str] = field(default_factory=dict)

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        form: dict[str, str] | None = None,
        payload: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        заголовки = dict(headers or {})
        данные: bytes | None = None
        if form is not None:
            данные = urllib.parse.urlencode(form).encode()
            заголовки["Content-Type"] = "application/x-www-form-urlencoded"
        elif payload is not None:
            данные = json.dumps(payload).encode()
            заголовки["Content-Type"] = "application/json"
        if self.cookies:
            заголовки["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        запрос = urllib.request.Request(url, data=данные, headers=заголовки, method=method)  # noqa: S310
        try:
            ответ = _OPENER.open(запрос, timeout=TIMEOUT_SEC)
        except urllib.error.HTTPError as отказ:
            ответ = отказ
        with ответ:
            тело = ответ.read().decode("utf-8", "replace")
            self._remember(ответ.headers)
            return Reply(int(ответ.status), ответ.headers, тело)

    def _remember(self, headers: Message) -> None:
        for строка in headers.get_all("Set-Cookie") or []:
            имя, _, остаток = строка.partition("=")
            self.cookies[имя.strip()] = остаток.split(";", 1)[0]


def _step(номер: int, что: str) -> None:
    print(f"[{номер}] {что}", flush=True)


def _need(условие: bool, причина: str) -> None:
    if not условие:
        raise SmokeError(причина)


def _origin(url: str) -> str:
    части = urllib.parse.urlsplit(url)
    return f"{части.scheme}://{части.netloc}"


def _rpc(b: Browser, mcp: str, token: str, method: str, rid: int) -> Reply:
    return b.request(
        mcp,
        method="POST",
        payload={"jsonrpc": "2.0", "id": rid, "method": method, "params": {}},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )


def _discover(b: Browser, admin: str, mcp: str) -> None:
    _step(1, "MCP без токена: 401 и документ ресурса")
    ответ = b.request(mcp, method="POST", payload={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    _need(ответ.status == 401, f"MCP без токена ответил {ответ.status}, ожидался 401")
    заголовок = ответ.headers.get("WWW-Authenticate") or ""
    найдено = re.search(r'resource_metadata="([^"]+)"', заголовок)
    if найдено is None:
        raise SmokeError("в WWW-Authenticate нет resource_metadata — MCP_PUBLIC_URL не задан?")
    документ = json.loads(b.request(найдено.group(1)).body)
    _need(
        документ.get("authorization_servers") == [admin],
        f"документ ресурса называет {документ.get('authorization_servers')}, а не {admin}",
    )
    _step(2, "метаданные сервера авторизации")
    мета = json.loads(b.request(f"{admin}/.well-known/oauth-authorization-server").body)
    _need(мета.get("issuer") == admin, f"issuer {мета.get('issuer')} вместо {admin}")
    _need(мета.get("code_challenge_methods_supported") == ["S256"], "S256 не объявлен")


def _register(b: Browser, admin: str) -> str:
    _step(3, "регистрация клиента (DCR)")
    ответ = b.request(
        f"{admin}/oauth/register",
        method="POST",
        payload={"client_name": "decimus oauth_smoke", "redirect_uris": [CALLBACK]},
    )
    _need(ответ.status == 201, f"регистрация ответила {ответ.status}: {ответ.body[:200]}")
    return str(json.loads(ответ.body)["client_id"])


def _login(b: Browser, admin: str, login: str, password: str) -> None:
    _step(4, f"вход учёткой {login}")
    ответ = b.request(
        f"{admin}/login",
        method="POST",
        form={"login": login, "password": password},
        headers={"Origin": _origin(admin)},
    )
    _need(
        ответ.status == 302 and SESSION_COOKIE in b.cookies,
        f"вход ответил {ответ.status} без куки сессии — логин, пароль или Origin",
    )


def _authorize(b: Browser, admin: str, mcp: str, client_id: str, challenge: str) -> tuple[str, str]:
    _step(5, "согласие → «Разрешить» → код")
    параметры = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": CALLBACK,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": secrets.token_urlsafe(8),
        "scope": "mcp",
        "resource": mcp,
    }
    страница = b.request(f"{admin}/oauth/authorize?{urllib.parse.urlencode(параметры)}")
    _need(страница.status == 200, f"страница согласия ответила {страница.status}")
    роль = re.search(r"(?:Ваша роль|Your role): ([^<.]+)", html.unescape(страница.body))
    ответ = b.request(
        f"{admin}/oauth/authorize",
        method="POST",
        form={**параметры, "decision": "allow"},
        headers={"Origin": _origin(admin)},
    )
    куда = ответ.headers.get("Location") or ""
    _need(ответ.status == 302 and куда.startswith(CALLBACK), f"«Разрешить» ответил {ответ.status}")
    запрос = urllib.parse.parse_qs(urllib.parse.urlsplit(куда).query)
    _need(запрос.get("state") == [параметры["state"]], "state вернулся не тот")
    _need("code" in запрос, f"кода в возврате нет: {запрос.get('error')}")
    return запрос["code"][0], роль.group(1).strip() if роль else "?"


def _token(b: Browser, admin: str, form: dict[str, str]) -> dict[str, Any]:
    ответ = b.request(f"{admin}/oauth/token", method="POST", form=form)
    _need(ответ.status == 200, f"выдача токенов ответила {ответ.status}: {ответ.body[:200]}")
    return dict(json.loads(ответ.body))


def _tools(b: Browser, mcp: str, access: str) -> list[str]:
    ответ = _rpc(b, mcp, access, "initialize", 1)
    _need(ответ.status == 200, f"initialize ответил {ответ.status}")
    ответ = _rpc(b, mcp, access, "tools/list", 2)
    _need(ответ.status == 200, f"tools/list ответил {ответ.status}")
    return sorted(t["name"] for t in json.loads(ответ.body)["result"]["tools"])


def _revoke(b: Browser, admin: str) -> None:
    _step(9, "отзыв подключения со своей карточки")
    карточка = b.request(f"{admin}/users?person=me")
    номера = re.findall(r'name="connection_id" value="([^"]+)"', карточка.body)
    _need(bool(номера), "на своей карточке нет подключений — блок не показан или список пуст")
    for номер in номера:
        ответ = b.request(
            f"{admin}/users/claude-revoke",
            method="POST",
            form={"connection_id": номер},
            headers={"Origin": _origin(admin)},
        )
        _need(ответ.status == 200, f"отзыв ответил {ответ.status}")


def run(admin: str, mcp: str, login: str, password: str) -> None:
    b = Browser()
    _discover(b, admin, mcp)
    client_id = _register(b, admin)
    _login(b, admin, login, password)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    код, роль = _authorize(b, admin, mcp, client_id, challenge)
    _step(6, "обмен кода (PKCE S256)")
    пара = _token(
        b,
        admin,
        {
            "grant_type": "authorization_code",
            "code": код,
            "client_id": client_id,
            "redirect_uri": CALLBACK,
            "code_verifier": verifier,
        },
    )
    _step(7, "MCP initialize + tools/list")
    инструменты = _tools(b, mcp, str(пара["access_token"]))
    print(f"    роль: {роль}; инструментов: {len(инструменты)}")
    for имя in инструменты:
        print(f"      {имя}")
    _step(8, "refresh → новая пара")
    новая = _token(
        b,
        admin,
        {
            "grant_type": "refresh_token",
            "refresh_token": str(пара["refresh_token"]),
            "client_id": client_id,
        },
    )
    _need(_tools(b, mcp, str(новая["access_token"])) == инструменты, "после refresh список другой")
    _revoke(b, admin)
    ответ = _rpc(b, mcp, str(новая["access_token"]), "ping", 3)
    _need(ответ.status == 401, f"после отзыва MCP ответил {ответ.status}, ожидался 401")
    print("    после отзыва MCP отвечает 401")


def main(argv: list[str] | None = None) -> int:
    разбор = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    разбор.add_argument("--admin", default=os.environ.get(ADMIN_VAR, ""))
    разбор.add_argument("--mcp", default=os.environ.get(MCP_VAR, ""))
    разбор.add_argument("--login", default="")
    аргументы = разбор.parse_args(argv)
    пароль = os.environ.get(PASSWORD_VAR, "")
    admin, mcp = аргументы.admin.rstrip("/"), аргументы.mcp.rstrip("/")
    if not admin or not mcp or not аргументы.login or not пароль:
        print(
            f"Нужны --admin (или {ADMIN_VAR}), --mcp (или {MCP_VAR}), --login и пароль "
            f"в {PASSWORD_VAR}",
            file=sys.stderr,
        )
        return 2
    try:
        run(admin, mcp, аргументы.login, пароль)
    except SmokeError as отказ:
        print(f"ПРОВАЛ: {отказ}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as отказ:
        print(f"ПРОВАЛ: {type(отказ).__name__}", file=sys.stderr)
        return 1
    print("OK: подключение Claude через сайт работает от входа до отзыва")
    return 0


if __name__ == "__main__":
    sys.exit(main())
