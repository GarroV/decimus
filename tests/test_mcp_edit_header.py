"""Правка шапки проверки через MCP: отказы до базы и права (без базы)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from src.mcp import imports as imports_module
from src.mcp import move as move_module
from src.mcp.catalogue import find
from src.mcp.errors import ToolError
from src.mcp.policy import permits_tool

ID = "00000000-0000-0000-0000-000000000001"
ЗАВТРА = (date.today() + timedelta(days=1)).isoformat()


def test_дата_в_будущем_у_черновика_отказана_до_базы(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_module, "_only_import", lambda *a, **k: (None, None))

    with pytest.raises(ToolError, match="в будущем"):
        imports_module.import_edit_inspection(
            tenant="HQ",
            store=object(),
            actor="a",
            inspection_id=ID,
            date=ЗАВТРА,  # type: ignore[arg-type]
        )


def test_правка_шапки_без_полей_отказана(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imports_module, "_only_import", lambda *a, **k: (None, None))

    with pytest.raises(ToolError, match="Нечего менять"):
        imports_module.import_edit_inspection(
            tenant="HQ",
            store=object(),
            actor="a",
            inspection_id=ID,  # type: ignore[arg-type]
        )


def test_перенос_принятой_без_полей_и_с_датой_в_будущем_отказан() -> None:
    with pytest.raises(ToolError, match="Нечего менять"):
        move_module.move_inspection(tenant="HQ", actor="a", inspection_id=ID, reason="x")
    with pytest.raises(ToolError, match="в будущем"):
        move_module.move_inspection(
            tenant="HQ", actor="a", inspection_id=ID, reason="x", date=ЗАВТРА
        )


@pytest.mark.parametrize(
    ("роль", "ожидание"),
    [("developer", True), ("admin", True), ("guest", False), ("auditor", False)],
)
def test_move_inspection_открыт_по_действию_матрицы(роль: str, ожидание: bool) -> None:
    spec: Any = find("move_inspection")

    assert permits_tool(роль, "HQ", spec) is ожидание
