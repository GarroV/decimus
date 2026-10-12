"""Третья дверь MCP — access-токен OAuth (D417) — на живом сервере.

Проверяется то, что видит Claude: 401 называет документ ресурса, документ
называет сервер авторизации, токен опознаётся в учётку с ролью, и права дальше
решает роль. Сверка токена в базе подменена на границе `src.db.oauth_store`
(живой путь до Postgres — `tests/test_db_oauth_store.py`).
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from src.db import oauth_store
from src.db.oauth_store import OAuthOwner
from src.mcp.catalogue import KIND_RATINGS, TOOLS
from src.mcp.config import MIN_TOKEN_LENGTH, Settings, resolve_access
from src.mcp.server import build_server

АДМИНКА = "https://admin.example"
MCP = "https://mcp.example/mcp"
ТОКЕН_ENV = "e" * MIN_TOKEN_LENGTH
ДОКУМЕНТ = "/.well-known/oauth-protected-resource"

#: Выданные «админкой» access-токены → учётка. Тест правит словарь: удалённый
#: токен — отозванное подключение или отключённая учётка.
ВЫДАННЫЕ: dict[str, OAuthOwner] = {}

#: Токены, выданные для ДРУГОГО ресурса (RFC 8707); остальные — для `MCP`.
ЧУЖОЙ_РЕСУРС = {"tok-other": "https://other.example/mcp"}


@pytest.fixture(autouse=True)
def _сверка_без_базы(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    зовы: list[str] = []

    def _resolve(token: str, *, resource: str) -> OAuthOwner | None:
        """Как запрос базы: токен находится, только если выдан для этого ресурса."""
        зовы.append(token)
        if ЧУЖОЙ_РЕСУРС.get(token, MCP) != resource:
            return None
        return ВЫДАННЫЕ.get(token)

    monkeypatch.setattr(oauth_store, "resolve_access_token", _resolve)
    ВЫДАННЫЕ.clear()
    ВЫДАННЫЕ.update(
        {
            "tok-control": OAuthOwner("u1", "kontrol", "HQ", "control"),
            "tok-admin": OAuthOwner("u2", "anna", "HQ", "admin"),
            "tok-auditor": OAuthOwner("u3", "ivan", "HQ", "auditor"),
            "tok-partner": OAuthOwner("u4", "petar", "RS", "admin"),
            "tok-other": OAuthOwner("u2", "anna", "HQ", "admin"),
        }
    )
    yield зовы
    ВЫДАННЫЕ.clear()


def _настройки(*, oauth: bool) -> Settings:
    return Settings(
        tokens={ТОКЕН_ENV: "HQ"},
        tenants=("HQ",),
        host="127.0.0.1",
        port=0,
        admin_public_url=АДМИНКА if oauth else None,
        mcp_public_url=MCP if oauth else None,
    )


def _поднять(settings: Settings) -> Iterator[str]:
    httpd = build_server(settings)
    поток = threading.Thread(target=httpd.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        поток.join(timeout=5)


@pytest.fixture
def сервер() -> Iterator[str]:
    yield from _поднять(_настройки(oauth=True))


@pytest.fixture
def сервер_без_oauth() -> Iterator[str]:
    yield from _поднять(_настройки(oauth=False))


def _http(
    адрес: str, *, метод: str = "POST", тело: Any = None, токен: str | None = None
) -> tuple[int, dict[str, str], str]:
    данные = None if тело is None else json.dumps(тело).encode()
    заголовки = {"Content-Type": "application/json"}
    if токен is not None:
        заголовки["Authorization"] = f"Bearer {токен}"
    запрос = urllib.request.Request(адрес, data=данные, headers=заголовки, method=метод)  # noqa: S310
    try:
        with urllib.request.urlopen(запрос, timeout=10) as ответ:  # noqa: S310
            return int(ответ.status), dict(ответ.headers), ответ.read().decode()
    except urllib.error.HTTPError as отказ:
        return int(отказ.code), dict(отказ.headers), отказ.read().decode()


def _инструменты(адрес: str, токен: str) -> set[str]:
    код, _, тело = _http(
        адрес + "/", тело={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, токен=токен
    )
    assert код == 200, тело
    return {t["name"] for t in json.loads(тело)["result"]["tools"]}


def _вызов(адрес: str, токен: str, имя: str) -> tuple[int, dict[str, Any]]:
    сообщение = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": имя, "arguments": {}},
    }
    код, _, тело = _http(адрес + "/", тело=сообщение, токен=токен)
    return код, json.loads(тело) if тело else {}


def test_токен_чужого_ресурса_не_опознаётся(сервер: str) -> None:
    """RFC 8707: токен, выданный для другого сервера, сюда не годится."""
    код, _, _ = _http(
        сервер + "/", тело={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, токен="tok-other"
    )

    assert код == 401
    assert _инструменты(сервер, "tok-admin")


# --- обнаружение -------------------------------------------------------------


def test_401_называет_документ_ресурса(сервер: str) -> None:
    код, заголовки, _ = _http(сервер + "/", тело={"jsonrpc": "2.0", "id": 1, "method": "ping"})

    assert код == 401
    assert f'resource_metadata="{MCP}{ДОКУМЕНТ}"' in заголовки["WWW-Authenticate"]


def test_без_oauth_401_как_раньше(сервер_без_oauth: str) -> None:
    _, заголовки, _ = _http(
        сервер_без_oauth + "/", тело={"jsonrpc": "2.0", "id": 1, "method": "ping"}
    )

    assert заголовки["WWW-Authenticate"] == 'Bearer realm="dodo-audit-mcp"'


@pytest.mark.parametrize("путь", [ДОКУМЕНТ, f"{ДОКУМЕНТ}/mcp", f"/mcp{ДОКУМЕНТ}"])
def test_документ_ресурса_называет_сервер_авторизации(сервер: str, путь: str) -> None:
    код, _, тело = _http(сервер + путь, метод="GET")

    assert код == 200
    документ = json.loads(тело)
    assert документ["resource"] == MCP
    assert документ["authorization_servers"] == [АДМИНКА]
    assert документ["scopes_supported"] == ["mcp"]


def test_без_oauth_документа_нет(сервер_без_oauth: str) -> None:
    код, _, _ = _http(сервер_без_oauth + ДОКУМЕНТ, метод="GET")

    assert код == 405


# --- права по роли через живой сервер ---------------------------------------


def test_контроль_видит_только_рейтинги(сервер: str) -> None:
    имена = _инструменты(сервер, "tok-control")

    assert имена == {spec.name for spec in TOOLS if spec.kind == KIND_RATINGS}


def test_контроль_не_читает_проверки(сервер: str) -> None:
    код, ответ = _вызов(сервер, "tok-control", "network_summary")

    assert код == 200
    assert ответ["result"]["isError"] is True


def test_админ_видит_больше_аудитора_а_аудитор_больше_партнёра(сервер: str) -> None:
    админ = _инструменты(сервер, "tok-admin")
    аудитор = _инструменты(сервер, "tok-auditor")
    партнёр = _инструменты(сервер, "tok-partner")

    assert партнёр < аудитор < админ
    assert "retract_inspection" not in админ


def test_токен_env_видит_каталог_целиком(сервер: str) -> None:
    assert _инструменты(сервер, ТОКЕН_ENV) == {spec.name for spec in TOOLS}


def test_отозванный_токен_получает_401_на_следующем_вызове(сервер: str) -> None:
    assert _инструменты(сервер, "tok-auditor")

    del ВЫДАННЫЕ["tok-auditor"]
    код, _, _ = _http(
        сервер + "/", тело={"jsonrpc": "2.0", "id": 1, "method": "ping"}, токен="tok-auditor"
    )

    assert код == 401


def test_смена_роли_видна_сразу(сервер: str) -> None:
    до = _инструменты(сервер, "tok-auditor")

    ВЫДАННЫЕ["tok-auditor"] = OAuthOwner("u3", "ivan", "HQ", "control")

    assert _инструменты(сервер, "tok-auditor") != до


def test_без_oauth_токен_сайта_не_сверяется(
    сервер_без_oauth: str, _сверка_без_базы: list[str]
) -> None:
    код, _, _ = _http(
        сервер_без_oauth + "/",
        тело={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        токен="tok-admin",
    )

    assert код == 401
    assert "tok-admin" not in _сверка_без_базы


def test_доступ_через_сайт_без_снятия_и_с_подписью() -> None:
    доступ = resolve_access(_настройки(oauth=True), "Bearer tok-admin")

    assert доступ.role == "admin"
    assert доступ.may_retract is False
    assert доступ.actor == "web:anna"
    assert доступ.tenant == "HQ"


def test_двери_env_роли_не_дают() -> None:
    assert resolve_access(_настройки(oauth=True), f"Bearer {ТОКЕН_ENV}").role is None
