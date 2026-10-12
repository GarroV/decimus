"""Личный токен Claude в своих настройках на сайте (D447, D448; аудит 12.10).

Права — ядро: ошибка здесь молча раздаёт доступ к истории проверок. Правило
D448: доступ к Claude никто никому не выдаёт — вошедший выпускает и отзывает
токен только СЕБЕ, учётка берётся из сессии, а не из формы; дверей «дать
доступ» и «снять доступ» другому человеку нет. Слой базы подменён на границе.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.db import mcp_access
from src.db.errors import DbError
from src.web import accounts

ЗАГОЛОВКИ = {"Origin": СВОЙ}
МОЙ_ID = Учётка().id
СРОК = datetime(2026, 11, 11, tzinfo=UTC)


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


@pytest.fixture
def токены(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменённое хранилище токенов: кому выпускали, у кого отзывали, что живо."""
    сост: dict[str, Any] = {"issued": [], "revoked": [], "live": {}}

    def выпустить(user_id: str, *, chat: int | None = None) -> mcp_access.IssuedToken:
        сост["issued"].append(user_id)
        сост["live"][user_id] = СРОК
        return mcp_access.IssuedToken(
            value=f"tok-SECRET-{len(сост['issued'])}",
            tenant="HQ",
            role="auditor",
            expires_at=СРОК,
            replaced_previous=len(сост["issued"]) > 1,
        )

    def отозвать(user_id: str, *, by: int = 0) -> int:
        сост["revoked"].append(user_id)
        return 1 if сост["live"].pop(user_id, None) else 0

    monkeypatch.setattr(mcp_access, "issue_for_account", выпустить)
    monkeypatch.setattr(mcp_access, "revoke_tokens", отозвать)
    monkeypatch.setattr(mcp_access, "live_token_expiry", lambda uid: сост["live"].get(uid))
    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda **_: (строка("petr"), строка("nino", tenant="GE"), строка("vika", role="control")),
    )
    return сост


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def админ_уК(monkeypatch: pytest.MonkeyPatch, токены: dict[str, Any]) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="admin")


@pytest.mark.parametrize(
    ("tenant", "role"),
    [("HQ", "auditor"), ("HQ", "control"), ("GE", "auditor"), ("GE", "admin"), ("HQ", "admin")],
)
def test_любая_роль_выпускает_токен_себе_сама(
    monkeypatch: pytest.MonkeyPatch, токены: dict[str, Any], tenant: str, role: str
) -> None:
    """Никто не выдаёт: учётки и её роли достаточно (D448). Права в Claude решает роль."""
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.post("/users/claude-token", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 200
        assert токены["issued"] == [МОЙ_ID]
        страница = ответ.get_data(as_text=True)
        assert "tok-SECRET-1" in страница, "команда с токеном не показана"
        assert "no-store" in ответ.headers.get("Cache-Control", ""), "команду с токеном кэшируют"


def test_учётка_выпуска_только_из_сессии(админ_уК: FlaskClient, токены: dict[str, Any]) -> None:
    """Поле `user_id` в форме не читается: выпустить токен другому отсюда нечем."""
    ответ = админ_уК.post("/users/claude-token", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 200 and токены["issued"] == [МОЙ_ID]


def test_команда_показана_один_раз(админ_уК: FlaskClient, токены: dict[str, Any]) -> None:
    админ_уК.post("/users/claude-token", headers=ЗАГОЛОВКИ)

    потом = админ_уК.get("/users?person=me").get_data(as_text=True)

    assert "tok-SECRET" not in потом, "команда с токеном осталась на странице"
    assert "2026-11-11" in потом, "срок живого токена не показан"


def test_свой_отзыв_и_только_свой(админ_уК: FlaskClient, токены: dict[str, Any]) -> None:
    админ_уК.post("/users/claude-token", headers=ЗАГОЛОВКИ)

    ответ = админ_уК.post(
        "/users/claude-token-revoke", data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200 and токены["revoked"] == [МОЙ_ID]
    assert токены["live"] == {}


@pytest.mark.parametrize("дверь", ["/users/mcp-grant", "/users/mcp-revoke"])
def test_дверей_выдачи_другому_больше_нет(админ_уК: FlaskClient, дверь: str) -> None:
    ответ = админ_уК.post(дверь, data={"user_id": "id-petr"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code in (404, 405)


def test_чужая_карточка_без_блока_токена(админ_уК: FlaskClient) -> None:
    страница = админ_уК.get("/users?person=id-petr").get_data(as_text=True)

    assert 'id="claude-token"' not in страница, "у чужой карточки кнопки токена"
    assert "Дать доступ" not in страница


def test_чужой_источник_не_выпускает(админ_уК: FlaskClient, токены: dict[str, Any]) -> None:
    ответ = админ_уК.post("/users/claude-token", headers={"Origin": "https://evil.example"})

    assert ответ.status_code in (400, 403) and токены["issued"] == []


def test_база_молчит_отказ_словами(
    админ_уК: FlaskClient, токены: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def молчит(*_: object, **__: object) -> None:
        raise DbError("нет базы")

    monkeypatch.setattr(mcp_access, "issue_for_account", молчит)

    ответ = админ_уК.post("/users/claude-token", headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 503
    assert "curl" not in ответ.get_data(as_text=True), "без токена ушла полкоманды"
