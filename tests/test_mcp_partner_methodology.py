"""D460: админ партнёра ведёт методику своего пространства и в Claude, как в вебе.

Ядро — права: ошибка здесь тихая (партнёр правит чужое или эталон УК, и никто не
увидит). Проверяется сквозь настоящую дверь: `Settings` без партнёра в
`MCP_CHECKLIST_TENANTS` (партнёров в базе много, список им не нужен), роль из входа
через OAuth, хранилище подставляет `server._checklist_for`, вызов идёт через `handle`.
Базы тестам не нужно.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, current_version, read_journal
from src.mcp.checklist_layout import read_meta
from src.mcp.checklists import create
from src.mcp.config import MIN_TOKEN_LENGTH, Settings
from src.mcp.rpc import ETALON_READONLY_FOR_PARTNER, ROLE_CLOSED, handle
from src.mcp.server import _checklist_for, _checklist_source_for

ПАРТНЁР = "GE"
ЧУЖОЙ = "AM"
СЕГОДНЯ = date(2026, 10, 13)

ПРАВКА_ЭТАЛОНА = {"checklist": "bizdev", "name_ru": "Захват"}


@pytest.fixture
def настройки(tmp_path: Path) -> Settings:
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    for space, tenant, code in (("ge", ПАРТНЁР, "own"), ("am", ЧУЖОЙ, "rnd")):
        create(
            replace(store, space=space, code=code),
            tenant=tenant,
            name_ru="Свой",
            name_en="Own",
            today=СЕГОДНЯ,
        )
    return Settings(
        tokens={"h" * MIN_TOKEN_LENGTH: "HQ"},
        tenants=("HQ",),
        host="127.0.0.1",
        port=0,
        checklist_store=store.root,
        # Партнёров в списке нет нарочно: их открывает роль, а не `.env`.
        checklist_tenants=("HQ",),
        data_dir=методика,
    )


def _вызов(
    имя: str, аргументы: dict[str, Any], настройки: Settings, *, role: str, tenant: str = ПАРТНЁР
) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=tenant,
        checklist=_checklist_for(настройки, tenant, role),
        source=_checklist_source_for(настройки, tenant, role),
        role=role,
    )
    assert ответ is not None
    return ответ


def _список(настройки: Settings, *, role: str, tenant: str = ПАРТНЁР) -> set[str]:
    ответ = handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        tenant=tenant,
        checklist=_checklist_for(настройки, tenant, role),
        source=_checklist_source_for(настройки, tenant, role),
        role=role,
    )
    assert ответ is not None
    return {t["name"] for t in ответ["result"]["tools"]}


def _текст(ответ: dict[str, Any]) -> str:
    return "".join(блок.get("text", "") for блок in ответ["result"]["content"])


def _store(настройки: Settings, *, space: str, code: str) -> Store:
    assert настройки.checklist_store is not None and настройки.data_dir is not None
    return Store(root=настройки.checklist_store, live=настройки.data_dir, space=space, code=code)


def test_админу_партнёра_в_tools_list_видна_методика(настройки: Settings) -> None:
    имена = _список(настройки, role="admin")

    assert {"checklists", "checklist_items", "edit_checklist_item", "checklist_source"} <= имена
    assert {"create_checklist", "publish_checklist_version"} <= имена
    assert "apply_checklist" not in имена


def test_сотруднику_партнёра_методика_не_видна(настройки: Settings) -> None:
    имена = _список(настройки, role="auditor")

    assert not имена & {"checklists", "edit_checklist_item", "checklist_source"}


def test_хранилище_партнёру_даёт_роль_а_не_список_env(настройки: Settings) -> None:
    своё = _checklist_for(настройки, ПАРТНЁР, "admin")
    assert своё is not None and своё.space == "ge"
    assert _checklist_for(настройки, ПАРТНЁР, "auditor") is None
    # Токен без роли (карта `.env`): решает список, как раньше, — партнёра в нём нет.
    assert _checklist_for(настройки, ПАРТНЁР, None) is None
    assert _checklist_source_for(настройки, ПАРТНЁР, None) is None
    эталон = _checklist_source_for(настройки, ПАРТНЁР, "admin")
    assert эталон is not None and эталон.space == "hq"


def test_админ_партнёра_правит_свой_чек_лист_в_своём_пространстве(настройки: Settings) -> None:
    ответ = _вызов(
        "rename_checklist", {"checklist": "own", "name_ru": "Новое"}, настройки, role="admin"
    )

    assert ответ["result"].get("isError") is not True
    assert json.loads(_текст(ответ))["space"] == "ge"
    assert read_meta(_store(настройки, space="ge", code="own")).name_ru == "Новое"


def test_админ_партнёра_заводит_чек_лист_только_у_себя(настройки: Settings) -> None:
    ответ = _вызов(
        "create_checklist",
        {"checklist": "second", "name_ru": "Второй", "name_en": "Second"},
        настройки,
        role="admin",
    )

    assert ответ["result"].get("isError") is not True, _текст(ответ)
    assert read_meta(_store(настройки, space="ge", code="second")).name_ru == "Второй"
    assert read_meta(_store(настройки, space="hq", code="second")) is None


def test_админ_партнёра_читает_эталон_но_не_правит_его(настройки: Settings) -> None:
    эталон = _store(настройки, space="hq", code="bizdev")
    журнал_до, карточка_до = read_journal(эталон), read_meta(эталон)

    чтение = _вызов("checklist_source", {}, настройки, role="admin")
    правка = _вызов("rename_checklist", ПРАВКА_ЭТАЛОНА, настройки, role="admin")

    assert чтение["result"].get("isError") is not True
    assert правка["result"].get("isError") is True
    assert _текст(правка) == ETALON_READONLY_FOR_PARTNER.format(код="bizdev")
    assert read_journal(эталон) == журнал_до
    assert read_meta(эталон) == карточка_до


def test_админ_партнёра_не_правит_чек_лист_чужого_партнёра(настройки: Settings) -> None:
    чужой = _store(настройки, space="am", code="rnd")
    карточка_до, журнал_до = read_meta(чужой), read_journal(чужой)

    ответ = _вызов(
        "rename_checklist", {"checklist": "rnd", "name_ru": "x"}, настройки, role="admin"
    )

    assert ответ["result"].get("isError") is True
    assert "в пространстве «ge» нет" in _текст(ответ)
    assert read_meta(чужой) == карточка_до
    assert read_journal(чужой) == журнал_до


def test_админ_партнёра_не_двигает_указатель_прода(настройки: Settings) -> None:
    ответ = _вызов("apply_checklist", {"checklist": "own"}, настройки, role="admin")

    assert ответ["result"].get("isError") is True
    assert "применяет только УК" in _текст(ответ)


def test_сотруднику_партнёра_вызов_методики_отказ_роли(настройки: Settings) -> None:
    ответ = _вызов(
        "rename_checklist", {"checklist": "own", "name_ru": "x"}, настройки, role="auditor"
    )

    assert ответ["result"].get("isError") is True
    assert _текст(ответ) == ROLE_CLOSED.format(роль="auditor")
    assert read_meta(_store(настройки, space="ge", code="own")).name_ru == "Свой"
