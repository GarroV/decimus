"""D440: бизнес-девелопер ведёт методику через MCP, но главный чек-лист ему закрыт словами.

Вид `checklist` роли открыт целиком, а «главный» — свойство чек-листа, поэтому
отказ стоит в `rpc._call_tool` и идёт по подставленному хранилищу: код в вызове
может быть не назван вовсе, и правка ушла бы в применённый к проду.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, current_version
from src.mcp.checklist_layout import for_code
from src.mcp.checklists import set_master
from src.mcp.rpc import MASTER_READONLY, handle

ГЛАВНЫЙ = "bizdev"
СВОЙ = "rnd"
НОВЫЙ = {"checklist": СВОЙ, "name_ru": "Аудит РНД", "name_en": "RnD audit"}
#: Начало отказа: по нему отказ главного отличают от любого другого отказа двери.
ОТКАЗ = MASTER_READONLY[:40]


@pytest.fixture
def хранилище(tmp_path: Path) -> Store:
    методика = build_methodology(tmp_path / "живая-методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    return store


def _вызвать(имя: str, аргументы: dict[str, Any], *, store: Store, роль: str) -> tuple[bool, str]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant="HQ",
        checklist=store,
        source=store,
        may_retract=False,
        role=роль,
    )
    assert ответ is not None
    результат = ответ["result"]
    текст = "".join(блок.get("text", "") for блок in результат["content"])
    return bool(результат.get("isError")), текст


def test_девелопер_заводит_свой_чек_лист(хранилище: Store) -> None:
    ошибка, текст = _вызвать("create_checklist", НОВЫЙ, store=хранилище, роль="developer")

    assert not ошибка, текст


@pytest.mark.parametrize("аргументы", [{"checklist": ГЛАВНЫЙ}, {}])
def test_девелопер_правку_главного_получает_отказом_словами(
    хранилище: Store, аргументы: dict[str, Any]
) -> None:
    """Код назван — главный; код не назван — применённый к проду, это тоже главный."""
    ошибка, текст = _вызвать("apply_checklist", аргументы, store=хранилище, роль="developer")

    assert ошибка
    assert ОТКАЗ in текст


def test_админ_того_же_вызова_отказа_главного_не_получает(хранилище: Store) -> None:
    _, текст = _вызвать("apply_checklist", {"checklist": ГЛАВНЫЙ}, store=хранилище, роль="admin")

    assert ОТКАЗ not in текст


def test_свой_чек_лист_девелопер_правит_а_отмеченный_главным_уже_нет(хранилище: Store) -> None:
    _вызвать("create_checklist", НОВЫЙ, store=хранилище, роль="developer")
    _, до = _вызвать("apply_checklist", {"checklist": СВОЙ}, store=хранилище, роль="developer")
    assert ОТКАЗ not in до, "неглавный чек-лист получил отказ главного"

    set_master(for_code(хранилище, СВОЙ), tenant="HQ", on=True, by="test")
    ошибка, после = _вызвать(
        "apply_checklist", {"checklist": СВОЙ}, store=хранилище, роль="developer"
    )

    assert ошибка
    assert ОТКАЗ in после


def test_читать_главный_девелоперу_можно(хранилище: Store) -> None:
    ошибка, текст = _вызвать(
        "checklist_items", {"checklist": ГЛАВНЫЙ}, store=хранилище, роль="developer"
    )

    assert not ошибка, текст
