"""Блок «Подключить Claude» на своей карточке и отзыв подключения (D417).

Права — ядро: ошибка здесь молча оставляет Claude доступ после «Отключить» или
даёт отключить чужое подключение. Хранилище OAuth подменено в памяти
(`oauth_harness`), правила — продуктовые.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from oauth_harness import ПамятьOAuth, _Подключение, подменить_oauth
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.web import accounts
from src.web.users_claude import claude_code_command

MCP = "https://mcp.example/mcp"
АДМИНКА = "https://admin.example"
МОЙ = Учётка().id
ЧУЖОЙ = "33333333-3333-3333-3333-333333333333"


def _строка(user_id: str, login: str, tenant: str, role: str) -> Any:
    return SimpleNamespace(
        login=login,
        role=role,
        tenant=tenant,
        email=None,
        id=user_id,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=None,
    )


@pytest.fixture
def память(monkeypatch: pytest.MonkeyPatch) -> ПамятьOAuth:
    память = подменить_oauth(monkeypatch)
    клиент = память.register_client(
        "Claude", ["https://claude.ai/api/mcp/auth_callback"], address="203.0.113.5"
    )
    сейчас = datetime.now(UTC)
    память.grants["мое-подключение"] = _Подключение(МОЙ, клиент, сейчас)
    память.grants["чужое-подключение"] = _Подключение(ЧУЖОЙ, клиент, сейчас)
    return память


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, oauth: bool = True
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda **_: (
            _строка(МОЙ, "director", tenant, role),
            _строка(ЧУЖОЙ, "petr", tenant, "auditor"),
        ),
    )
    приложение = собрать(
        tenant="HQ",
        admin_public_url=АДМИНКА if oauth else None,
        mcp_public_url=MCP if oauth else None,
    )
    with приложение.test_client() as client:
        assert войти(client).status_code == 302
        yield client


РОЛИ = [
    ("HQ", "developer"),
    ("HQ", "admin"),
    ("HQ", "control"),
    ("HQ", "superadmin"),
    ("RS", "admin"),
    ("RS", "auditor"),
]


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_блок_есть_на_своей_карточке_любой_роли(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.get("/users?person=me")
        страница = ответ.get_data(as_text=True)

        assert ответ.status_code == 200, (tenant, role)
        assert 'id="claude-connect"' in страница
        assert MCP in страница
        assert claude_code_command(MCP) in страница
        assert "Коннекторы" in страница
        assert "мое-подключение" in страница
        assert "чужое-подключение" not in страница


def test_без_oauth_блока_нет(monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin", oauth=False):
        страница = client.get("/users?person=me").get_data(as_text=True)

        assert 'id="claude-connect"' not in страница
        assert client.post("/users/claude-revoke", headers={"Origin": СВОЙ}).status_code == 404


def test_на_чужой_карточке_блока_нет(monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="superadmin"):
        страница = client.get(f"/users?person={ЧУЖОЙ}").get_data(as_text=True)

        assert 'id="claude-connect"' not in страница


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_своё_подключение_отключается(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.post(
            "/users/claude-revoke",
            data={"connection_id": "мое-подключение"},
            headers={"Origin": СВОЙ},
        )

        assert ответ.status_code == 200, (tenant, role)
        assert память.grants["мое-подключение"].revoked is True
        assert "мое-подключение" not in ответ.get_data(as_text=True)


def test_чужое_подключение_не_отключается(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="superadmin"):
        ответ = client.post(
            "/users/claude-revoke",
            data={"connection_id": "чужое-подключение", "user_id": ЧУЖОЙ},
            headers={"Origin": СВОЙ},
        )

        assert память.grants["чужое-подключение"].revoked is False
        assert "Такого подключения у вас нет" in ответ.get_data(as_text=True)


def test_отключение_без_origin_отвергается(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="developer"):
        ответ = client.post("/users/claude-revoke", data={"connection_id": "мое-подключение"})

        assert ответ.status_code == 403
        assert память.grants["мое-подключение"].revoked is False
