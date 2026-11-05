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

from src.db import oauth_store
from src.db.errors import DbError
from src.web import accounts, users_mcp

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
def test_блок_есть_в_настройках_любой_роли(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.get("/settings?tile=claude")
        страница = ответ.get_data(as_text=True)

        assert ответ.status_code == 200, (tenant, role)
        assert 'id="claude-connect"' in страница
        assert MCP in страница
        assert "Подключено" in страница, "общий список подключений (D695)"
        assert "мое-подключение" in страница
        assert "чужое-подключение" not in страница


def test_без_oauth_блока_нет(monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin", oauth=False):
        страница = client.get("/settings?tile=claude").get_data(as_text=True)

        assert 'id="claude-connect"' not in страница
        assert client.post("/settings/claude-revoke", headers={"Origin": СВОЙ}).status_code == 404


def test_на_чужой_карточке_блока_нет(monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="superadmin"):
        страница = client.get(f"/administration?tab=people&person={ЧУЖОЙ}").get_data(as_text=True)

        assert 'id="claude-connect"' not in страница


@pytest.mark.parametrize(("tenant", "role"), РОЛИ)
def test_своё_подключение_отключается(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth, tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        ответ = client.post(
            "/settings/claude-revoke",
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
            "/settings/claude-revoke",
            data={"connection_id": "чужое-подключение", "user_id": ЧУЖОЙ},
            headers={"Origin": СВОЙ},
        )

        assert память.grants["чужое-подключение"].revoked is False
        assert "Такого подключения у вас нет" in ответ.get_data(as_text=True)


def test_отключение_без_origin_отвергается(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="developer"):
        ответ = client.post("/settings/claude-revoke", data={"connection_id": "мое-подключение"})

        assert ответ.status_code == 403
        assert память.grants["мое-подключение"].revoked is False


# --- плитка «Нейросети» (D695) -----------------------------------------------


def _подключить(память: ПамятьOAuth, ключ: str, имя: str, возврат: str) -> None:
    клиент = память.register_client(имя, [возврат], address="203.0.113.7")
    память.grants[ключ] = _Подключение(МОЙ, клиент, datetime.now(UTC))


def test_плитка_называется_нейросети_и_список_из_четырёх(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings?tile=claude").get_data(as_text=True)
        по_английски = client.get("/settings?tile=claude&lang=en").get_data(as_text=True)

        assert "<b>Нейросети</b>" in страница and "Claude (MCP)" not in страница
        assert "<b>AI assistants</b>" in по_английски
        assert страница.count("<option") == 4, "список выбора из четырёх нейросетей, не ряд чипов"
        for имя in ("ChatGPT", "Claude", "GLM (Z.ai)", "Kimi (Moonshot)"):
            assert f">{имя}</option>" in страница


@pytest.mark.parametrize(
    ("ai", "есть", "нет"),
    [
        (
            "chatgpt",
            [
                "Настольный ChatGPT на Mac",
                "вкладке Work",
                "Получить команду",
                "Обычные чаты и ChatGPT в браузере",
                "администратор рабочего пространства",
                "claude-mcp-url",
            ],
            ["claude mcp add", "codex mcp", "Add custom MCP server", "Add server"],
        ),
        (
            "claude",
            ["claude mcp add --transport http decimus " + MCP, "Получить команду установки"],
            ["codex mcp"],
        ),
        ("glm", ["chat.z.ai", "ZCode", "GLM Coding Plan"], ["codex mcp"]),
        ("kimi", ["kimi.com", "Kimi Code CLI", "/mcp-config login decimus"], ["codex mcp"]),
        ("неизвестная", ["claude mcp add --transport http decimus " + MCP], ["codex mcp"]),
    ],
)
def test_инструкция_выбранной_нейросети(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth, ai: str, есть: list[str], нет: list[str]
) -> None:
    monkeypatch.setattr(users_mcp, "own_status", lambda _id: users_mcp.TokenStatus(known=True))
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get(f"/settings?tile=claude&ai={ai}").get_data(as_text=True)

        for фраза in есть:
            assert фраза in страница, (ai, фраза)
        for фраза in нет:
            assert фраза not in страница, (ai, фраза)
        assert страница.count("<option") == 4


def test_chatgpt_оговорка_про_администратора_пространства_под_значком(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings?tile=claude&ai=chatgpt").get_data(as_text=True)

        assert "только администратор рабочего пространства ChatGPT" in страница
        assert страница.index("info-tip__pop") < страница.index("только администратор рабочего")


def test_без_oauth_адреса_и_команд_нет_а_токен_desktop_есть(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    monkeypatch.setattr(users_mcp, "own_status", lambda _id: users_mcp.TokenStatus(known=True))
    for client in _стенд(monkeypatch, tenant="HQ", role="admin", oauth=False):
        чат = client.get("/settings?tile=claude&ai=chatgpt").get_data(as_text=True)
        клод = client.get("/settings?tile=claude").get_data(as_text=True)

        assert "codex mcp" not in чат and "не включено" in чат
        assert "Получить команду" in чат, "настольному ChatGPT OAuth стенда не нужен"
        assert "Получить команду установки" in клод and "claude mcp add" not in клод


def test_подключено_называет_вид_по_адресу_а_имя_подписью(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    _подключить(память, "gpt", "Claude", "https://chatgpt.com/connector/oauth/abc")
    _подключить(память, "cli", "ChatGPT", "http://localhost:1455/oauth/callback")
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        страница = client.get("/settings?tile=claude").get_data(as_text=True)

        assert "<b>ChatGPT</b>" in страница and "называет себя «Claude»" in страница
        assert "<b>Программа на этом компьютере" in страница
        assert "называет себя «ChatGPT»" in страница
        assert страница.count("Отключить") == 3, "своё подключение Claude и два новых"
        assert "вызовов ещё не было" in страница


def test_подключено_пусто_и_неизвестно(
    monkeypatch: pytest.MonkeyPatch, память: ПамятьOAuth
) -> None:
    память.grants.clear()
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        пусто = client.get("/settings?tile=claude").get_data(as_text=True)
        assert "Подключений пока нет." in пусто

        def сбой(_id: str) -> None:
            raise DbError("база не ответила")

        monkeypatch.setattr(oauth_store, "list_connections", сбой)
        неизвестно = client.get("/settings?tile=claude").get_data(as_text=True)

        assert "база не ответила" in неизвестно and "Подключений пока нет." not in неизвестно
