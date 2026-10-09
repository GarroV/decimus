"""Доступ к Claude (MCP) из карточки человека: кто может дать и снять (#583, D099).

Права — ядро: ошибка здесь молча раздаёт доступ к истории проверок. Правило то
же, что в боте: круг плоский, правит его тот, кто в нём состоит (его СВОЙ
Telegram в круге или он основатель из настройки стенда); основателя не снять.
Веб дополнительно сужает: чужие привязки видят только главный админ и админ УК,
и цель обязана быть в их охвате. Слой базы подменён на границе.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.db import bot_links, mcp_access
from src.web import accounts

ЗАГОЛОВКИ = {"Origin": СВОЙ}
МОЙ_TG = 1001
ЕГО_TG = 2002


def строка(login: str, *, tenant: str = "HQ", role: str = "auditor") -> Any:
    return SimpleNamespace(
        login=login,
        role=role,
        tenant=tenant,
        email=None,
        id=f"id-{login}",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=None,
    )


def привязка(user_id: str, tg: int) -> bot_links.Binding:
    return bot_links.Binding(tg, user_id, "x", "HQ", datetime(2026, 9, 1, tzinfo=UTC))


@pytest.fixture
def круг(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменённый круг: кто в нём и кого звали дверями записи."""
    сост: dict[str, Any] = {"live": {МОЙ_TG}, "add": [], "revoke": []}
    привязки = {Учётка().id: привязка(Учётка().id, МОЙ_TG), "id-petr": привязка("id-petr", ЕГО_TG)}
    monkeypatch.setattr(bot_links, "binding_of", lambda uid: привязки.get(uid))
    monkeypatch.setattr(bot_links, "live_bindings", lambda: привязки)
    monkeypatch.setattr(mcp_access, "is_admin", lambda tg: tg in сост["live"])
    monkeypatch.setattr(mcp_access, "list_admins", lambda: [])
    monkeypatch.setattr(
        mcp_access, "add_admin", lambda tg, *, by: сост["add"].append((tg, by)) or True
    )

    def _снять(tg: int, *, by: int) -> mcp_access.Revocation:
        сост["revoke"].append((tg, by))
        return mcp_access.Revocation(tg, was_admin=True, tokens_revoked=1)

    monkeypatch.setattr(mcp_access, "revoke_access", _снять)
    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda **_: (строка("petr"), строка("nino", tenant="GE"), строка("vika", role="control")),
    )
    monkeypatch.setenv("BOT_MCP_OWNER_ID", "")
    return сост


def стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    # Двери опознания подменяют привязку «никто не привязан» — вернуть круговую:
    # иначе отказ шёл бы от «нет бота», а не от охвата, и тест ничего не держал бы.
    привязки = {Учётка().id: привязка(Учётка().id, МОЙ_TG), "id-petr": привязка("id-petr", ЕГО_TG)}
    monkeypatch.setattr(bot_links, "binding_of", lambda uid: привязки.get(uid))
    monkeypatch.setattr(bot_links, "live_bindings", lambda: привязки)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def админ_уК(monkeypatch: pytest.MonkeyPatch, круг: dict[str, Any]) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    привязки = {Учётка().id: привязка(Учётка().id, МОЙ_TG), "id-petr": привязка("id-petr", ЕГО_TG)}
    monkeypatch.setattr(bot_links, "binding_of", lambda uid: привязки.get(uid))
    monkeypatch.setattr(bot_links, "live_bindings", lambda: привязки)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_вошедший_в_круге_даёт_доступ_человеку_с_ботом(
    админ_уК: FlaskClient, круг: dict[str, Any]
) -> None:
    ответ = админ_уК.post("/users/mcp-grant", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200
    assert круг["add"] == [(ЕГО_TG, МОЙ_TG)]


def test_вне_круга_дать_и_снять_нельзя(админ_уК: FlaskClient, круг: dict[str, Any]) -> None:
    круг["live"].clear()

    дать = админ_уК.post("/users/mcp-grant", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)
    снять = админ_уК.post("/users/mcp-revoke", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)

    assert (дать.status_code, снять.status_code) == (403, 403)
    assert круг["add"] == [] and круг["revoke"] == []


def test_человек_без_бота_доступа_не_получает(админ_уК: FlaskClient, круг: dict[str, Any]) -> None:
    ответ = админ_уК.post("/users/mcp-grant", data={"user_id": "id-nino"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403 and круг["add"] == []


def test_основателя_круга_не_снять(
    админ_уК: FlaskClient, круг: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_MCP_OWNER_ID", str(ЕГО_TG))

    ответ = админ_уК.post("/users/mcp-revoke", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 400 and круг["revoke"] == []


def test_снятие_гасит_доступ_одним_движением(админ_уК: FlaskClient, круг: dict[str, Any]) -> None:
    ответ = админ_уК.post("/users/mcp-revoke", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200 and круг["revoke"] == [(ЕГО_TG, МОЙ_TG)]


@pytest.mark.parametrize(
    ("tenant", "role"), [("HQ", "control"), ("GE", "admin"), ("HQ", "auditor")]
)
def test_кто_не_видит_чужих_привязок_кругом_не_правит(
    monkeypatch: pytest.MonkeyPatch, круг: dict[str, Any], tenant: str, role: str
) -> None:
    for client in стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.post("/users/mcp-grant", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)
        assert ответ.status_code in (403, 404)
    assert круг["add"] == []
