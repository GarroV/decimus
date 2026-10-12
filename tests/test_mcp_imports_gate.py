"""Право на загрузку исторических проверок (D305) и подпись подтверждающего (D308).

Права — ядро: инструменты загрузки пишут в базу. Право открывается пространству
переменной `MCP_IMPORT_TENANTS` и спрашивается на входе (`rpc._call_tool`), а
подпись приходит из токена, не из аргументов. Базы этим тестам не нужно: заслон
стоит раньше обработчика.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp import config
from src.mcp.checklist import Store
from src.mcp.config import load_settings, resolve_access
from src.mcp.errors import McpConfigError
from src.mcp.rpc import IMPORT_CLOSED, handle
from src.mcp.server import _imports_for

ТОКЕН_УК = "hq-token-" + "x" * 24
ТОКЕН_GE = "ge-token-" + "y" * 24


def _env(tmp_path: Path, **ещё: str) -> dict[str, str]:
    методика = build_methodology(tmp_path / "live")
    return {
        "MCP_TOKENS": f"HQ={ТОКЕН_УК},GE={ТОКЕН_GE}",
        "MCP_CHECKLIST_STORE": str(tmp_path / "store"),
        "MCP_CHECKLIST_TENANTS": "HQ",
        "AUDIT_DATA_DIR": str(методика),
        **ещё,
    }


def _вызов(имя: str, **права: Any) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": {}},
        },
        tenant="HQ",
        **права,
    )
    assert ответ is not None
    return ответ


def test_загрузка_без_хранилища_методики_отказ_на_старте() -> None:
    with pytest.raises(McpConfigError, match="MCP_IMPORT_TENANTS"):
        load_settings({"MCP_TOKENS": f"HQ={ТОКЕН_УК}", "MCP_IMPORT_TENANTS": "HQ"})


def test_загрузка_открыта_только_названному_пространству(tmp_path: Path) -> None:
    # Arrange
    настройки = load_settings(_env(tmp_path, MCP_IMPORT_TENANTS="HQ"))

    # Act / Assert
    assert настройки.may_import("HQ")
    assert not настройки.may_import("GE")
    assert isinstance(_imports_for(настройки, "HQ"), Store)
    assert _imports_for(настройки, "GE") is None


def test_без_переменной_загрузка_закрыта_всем(tmp_path: Path) -> None:
    настройки = load_settings(_env(tmp_path))
    assert not настройки.may_import("HQ")
    assert _imports_for(настройки, "HQ") is None


@pytest.mark.parametrize(
    "имя",
    ["import_list_drafts", "import_create_inspection", "import_accept_inspection"],
)
def test_закрытая_загрузка_отказывает_до_обработчика(имя: str, tmp_path: Path) -> None:
    # Act — права нет: транспорт не подставил хранилище.
    ответ = _вызов(имя, imports=None, actor="mcp:HQ")

    # Assert — отказ доступа, а не разбор аргументов и не поход в базу.
    assert ответ["result"]["isError"] is True
    assert ответ["result"]["content"][0]["text"] == IMPORT_CLOSED


def test_без_подписи_загрузка_тоже_закрыта(tmp_path: Path) -> None:
    склад = Store(root=tmp_path / "store", live=build_methodology(tmp_path / "live"))
    ответ = _вызов("import_list_drafts", imports=склад, actor="")
    assert ответ["result"]["content"][0]["text"] == IMPORT_CLOSED


def test_открытая_загрузка_доходит_до_обработчика(tmp_path: Path) -> None:
    """Контроль к тестам выше: с правом отказ уже не про доступ (базы здесь нет)."""
    склад = Store(root=tmp_path / "store", live=build_methodology(tmp_path / "live"))
    ответ = _вызов("import_list_drafts", imports=склад, actor="mcp:HQ")
    текст = ответ["result"]["content"][0]["text"]
    assert текст != IMPORT_CLOSED
    assert "DATABASE_URL" in текст


def test_подпись_стороннего_токена_по_стороне(tmp_path: Path) -> None:
    настройки = load_settings(_env(tmp_path))
    доступ = resolve_access(настройки, f"Bearer {ТОКЕН_GE}")
    assert (доступ.tenant, доступ.actor) == ("GE", "mcp:GE")


def test_подпись_личного_токена_по_телеграму(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — личный токен, выпущенный ботом (T253): владелец из базы.
    настройки = load_settings(_env(tmp_path))
    monkeypatch.setattr(config, "_owner_from_store", lambda _токен: ("HQ", 4242))

    # Act
    доступ = resolve_access(настройки, "Bearer personal-" + "z" * 30)

    # Assert
    assert (доступ.tenant, доступ.actor) == ("HQ", "mcp:tg:4242")


# --- D335: загрузка задним числом только у УК, держит код ----------------------


@pytest.mark.parametrize("названо", ["GE", "HQ,GE", "default,RS", "hq"])
def test_загрузка_не_HQ_отказ_на_старте(tmp_path: Path, названо: str) -> None:
    with pytest.raises(McpConfigError, match="только УК"):
        load_settings(_env(tmp_path, MCP_IMPORT_TENANTS=названо))


def test_старый_код_УК_переводится_и_открывает_загрузку(tmp_path: Path) -> None:
    настройки = load_settings(_env(tmp_path, MCP_IMPORT_TENANTS="default"))
    assert настройки.import_tenants == ("HQ",)
    assert настройки.may_import("HQ") and настройки.may_import("default")


def test_пустая_переменная_выключатель_загрузки(tmp_path: Path) -> None:
    настройки = load_settings(_env(tmp_path, MCP_IMPORT_TENANTS=" , "))
    assert настройки.import_tenants == ()
    assert not настройки.may_import("HQ")


def test_методика_по_старому_коду_УК(tmp_path: Path) -> None:
    """`may_manage_checklist` переводит код, как `may_import` (D335)."""
    настройки = load_settings(_env(tmp_path))
    assert настройки.may_manage_checklist("HQ")
    assert настройки.may_manage_checklist("default")
    assert not настройки.may_manage_checklist("GE")
