"""Журнал действий на двери MCP (D462): кого и что пишет `journal_write_call`.

Чистый Python: запись в базу подменена. Ядро: журнал ведётся по человеку (учётка
сайта с ролью админа или главного админа), а не по служебному токену, и читающие
инструменты в него не попадают.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.db import journals
from src.mcp.audit import journal_write_call
from src.mcp.config import Access

ПАРОЛЬ = "ПАРОЛЬ-ИЗ-АРГУМЕНТОВ-ВЫЗОВА"


def _вызов(name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _доступ(role: str | None = "admin", user_id: str = "u-1") -> Access:
    return Access(
        tenant="HQ",
        may_retract=False,
        actor="web:anna",
        role=role,
        user_id=user_id,
        credential="pt:abcd1234",
    )


@pytest.fixture
def записи(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    собрано: list[dict[str, Any]] = []
    monkeypatch.setattr(journals, "record_action", lambda **kw: собрано.append(kw))
    return собрано


def test_изменяющий_вызов_админа_записан_с_человеком_адресом_и_исходом(
    записи: list[dict[str, Any]],
) -> None:
    ответ = {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "isError": False}}

    journal_write_call(
        _вызов("publish_checklist_version", checklist="main"),
        ответ,
        access=_доступ(),
        ip="198.51.100.7",
    )

    (запись,) = записи
    assert запись["action"] == "publish_checklist_version"
    assert запись["user_id"] == "u-1"
    assert запись["role"] == "admin"
    assert запись["door"] == "mcp"
    assert запись["ip"] == "198.51.100.7"
    assert запись["credential"] == "pt:abcd1234"
    assert запись["outcome"] == "ok"
    assert "checklist=main" in запись["target"]


def test_ошибка_инструмента_и_отказ_записаны_как_failed_и_rejected(
    записи: list[dict[str, Any]],
) -> None:
    упал = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True}}
    отказ = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "нет"}}

    journal_write_call(_вызов("apply_checklist"), упал, access=_доступ(), ip=None)
    journal_write_call(_вызов("apply_checklist"), отказ, access=_доступ(), ip=None)

    assert [z["outcome"] for z in записи] == ["failed", "rejected"]


def test_секрет_из_аргументов_вызова_не_записан(записи: list[dict[str, Any]]) -> None:
    journal_write_call(
        _вызов("create_checklist", password=ПАРОЛЬ, token=ПАРОЛЬ, code="x"),
        None,
        access=_доступ(),
        ip=None,
    )

    (запись,) = записи
    assert ПАРОЛЬ not in repr(запись)
    assert "code=x" in запись["target"]


@pytest.mark.parametrize("инструмент", ["list_inspections", "get_inspection", "ratings_summary"])
def test_читающие_инструменты_не_пишутся(записи: list[dict[str, Any]], инструмент: str) -> None:
    journal_write_call(_вызов(инструмент), None, access=_доступ(), ip=None)

    assert записи == []


@pytest.mark.parametrize("роль", ["developer", "control", "guest", "auditor", None])
def test_вызовы_прочих_ролей_не_пишутся(записи: list[dict[str, Any]], роль: str | None) -> None:
    journal_write_call(_вызов("apply_checklist"), None, access=_доступ(role=роль), ip=None)

    assert записи == []


def test_служебный_токен_без_учётки_не_пишется(записи: list[dict[str, Any]]) -> None:
    journal_write_call(_вызов("apply_checklist"), None, access=_доступ(user_id=""), ip=None)

    assert записи == []


@pytest.mark.parametrize(
    "сообщение",
    [
        None,
        [],
        {"method": "tools/list"},
        {"method": "tools/call", "params": {"name": "нет-такого"}},
    ],
)
def test_не_вызов_инструмента_не_пишется(записи: list[dict[str, Any]], сообщение: object) -> None:
    journal_write_call(сообщение, None, access=_доступ(), ip=None)

    assert записи == []
