"""MCP `create_unit`: видят только роли с `unit.create`; правила имени и дубль — как у веба."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.db import directory, unit_profiles
from src.db.errors import UnitExistsError
from src.mcp.errors import ToolError
from src.mcp.imports import create_unit
from src.mcp.rpc import handle


def _список(role: str) -> set[str]:
    ответ = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, tenant="HQ", role=role)
    assert ответ is not None
    return {t["name"] for t in ответ["result"]["tools"]}


def test_developer_видит_create_unit_а_партнёр_нет() -> None:
    assert "create_unit" in _список("developer")
    assert "create_unit" not in _список("guest")
    assert "create_unit" not in _список("control")


def _вызвать(**аргументы: Any) -> dict[str, object]:
    return create_unit(tenant="HQ", store=None, actor="dev", **аргументы)  # type: ignore[arg-type]


def test_заводит_пиццерию_и_отдаёт_каноническое_имя(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(unit_profiles, "by_country", lambda _c: ())
    заведённые: list[tuple[str, str]] = []

    def _создать(name: str, *, country: str, **_: Any) -> Any:
        заведённые.append((name, country))
        return SimpleNamespace(id="u-1")

    monkeypatch.setattr(directory, "create_unit", _создать)

    ответ = _вызвать(country="rs", name="belgrade 3")

    assert ответ == {"unit": "Belgrade-3", "country": "RS", "id": "u-1"}
    assert заведённые == [("Belgrade-3", "RS")]


def test_дубль_отказ_с_существующей_точкой(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(unit_profiles, "by_country", lambda _c: ())

    def _дубль(*_: Any, **__: Any) -> Any:
        raise UnitExistsError("есть", unit_id="u-9", name="Belgrade-3", country="RS")

    monkeypatch.setattr(directory, "create_unit", _дубль)

    with pytest.raises(ToolError, match="Belgrade-3"):
        _вызвать(country="RS", name="Belgrade-3")


def test_незнакомый_город_требует_подтверждения(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(unit_profiles, "by_country", lambda _c: ())
    monkeypatch.setattr(directory, "create_unit", lambda *_a, **_k: SimpleNamespace(id="u-2"))

    with pytest.raises(ToolError, match="confirm_new_city"):
        _вызвать(country="RS", name="Zemun 2")
    assert _вызвать(country="RS", name="Zemun 2", confirm_new_city=True)["id"] == "u-2"
