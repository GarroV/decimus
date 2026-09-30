"""Волна 1 (#340): MCP правит методику только в пространстве токена.

Задача 1 навела хранилище и раскладку на пространства; здесь пространство
доезжает до точки входа сервера (`_checklist_for`, `_checklist_source_for`) и
до разбора вызова (`rpc._aimed`): правка партнёра адресуется в его
пространство, а не в эталон УК, и правящий инструмент без кода в чужом для
эталона пространстве отказывает явно, а не молча уходит в применённый к проду
чек-лист УК.

Отдельно проверяется preflight-находка Н1: `checklists` и `checklist_meta` —
читатели уровня хранилища, а не уровня чек-листа, и общий заслон «без кода не
уходим в пространство партнёра» на них не распространяется — иначе партнёр не
получил бы даже перечень своих чек-листов, которого спросил, чтобы код узнать.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, current_version, read_journal
from src.mcp.checklists import create
from src.mcp.config import MIN_TOKEN_LENGTH, Settings
from src.mcp.rpc import NAME_THE_CHECKLIST, handle
from src.mcp.server import _checklist_for, _checklist_source_for

ПАРТНЁР = "GE"
СЕГОДНЯ = date(2026, 9, 30)


@pytest.fixture
def настройки(tmp_path: Path) -> Settings:
    методика = build_methodology(tmp_path / "методика")
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    create(
        replace(store, space="ge", code="own"),
        tenant=ПАРТНЁР,
        name_ru="Свой",
        name_en="Own",
        today=СЕГОДНЯ,
    )
    create(
        replace(store, space="am", code="rnd"),
        tenant="AM",
        name_ru="РНД",
        name_en="RnD",
        today=СЕГОДНЯ,
    )
    return Settings(
        tokens={"p" * MIN_TOKEN_LENGTH: ПАРТНЁР},
        tenants=(ПАРТНЁР,),
        host="127.0.0.1",
        port=0,
        checklist_store=store.root,
        # Правка партнёру открыта нарочно: проверяется, КУДА она попадает.
        checklist_tenants=(ПАРТНЁР,),
        data_dir=методика,
    )


def _вызов(имя: str, аргументы: dict[str, Any], настройки: Settings) -> dict[str, Any]:
    ответ = handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": имя, "arguments": аргументы},
        },
        tenant=ПАРТНЁР,
        checklist=_checklist_for(настройки, ПАРТНЁР),
        source=_checklist_source_for(настройки, ПАРТНЁР),
    )
    assert ответ is not None
    return ответ


def _текст(ответ: dict[str, Any]) -> str:
    return "".join(блок.get("text", "") for блок in ответ["result"]["content"])


def test_правка_партнёра_наведена_на_его_пространство(настройки: Settings) -> None:
    store = _checklist_for(настройки, ПАРТНЁР)
    assert store is not None and store.space == "ge"


def test_исходник_эталона_читается_из_пространства_уК(настройки: Settings) -> None:
    store = _checklist_source_for(настройки, ПАРТНЁР)
    assert store is not None and store.space == "hq"


def test_правящий_инструмент_без_кода_не_уходит_в_эталон(настройки: Settings) -> None:
    """Review Focus 4."""
    assert настройки.checklist_store is not None and настройки.data_dir is not None
    эталон = Store(
        root=настройки.checklist_store, live=настройки.data_dir, space="hq", code="bizdev"
    )
    было = len(read_journal(эталон))
    ответ = _вызов("set_checklist_state", {"state": "retired"}, настройки)
    assert ответ["result"].get("isError") is True
    assert NAME_THE_CHECKLIST in _текст(ответ)
    assert len(read_journal(эталон)) == было


def test_код_эталона_в_правящем_инструменте_это_не_найден(настройки: Settings) -> None:
    ответ = _вызов("set_checklist_state", {"checklist": "bizdev", "state": "retired"}, настройки)
    assert ответ["result"].get("isError") is True
    assert "нет" in _текст(ответ)


def test_перечень_партнёра_без_чужих_пространств(настройки: Settings) -> None:
    текст = _текст(_вызов("checklists", {}, настройки))
    assert "rnd" not in текст
    assert "own" in текст and "bizdev" in текст


# --- preflight Н1: списочные инструменты кода не требуют ----------------------


def test_перечень_партнёра_без_кода_это_не_назовите_чеклист(настройки: Settings) -> None:
    """`checklists` существует затем, чтобы код УЗНАТЬ: общий заслон на неё не
    распространяется, иначе партнёр не увидел бы даже список своих чек-листов."""
    ответ = _вызов("checklists", {}, настройки)
    assert ответ["result"].get("isError") is not True
    assert NAME_THE_CHECKLIST not in _текст(ответ)


def test_карточка_партнёра_без_кода_это_не_назовите_чеклист(настройки: Settings) -> None:
    """`checklist_meta` без кода допустимо ответить «не найден» (кода «bizdev»
    в пространстве партнёра нет), но не общим заслоном «назовите чек-лист»:
    у неё код тоже не обязателен (preflight Н1)."""
    ответ = _вызов("checklist_meta", {}, настройки)
    assert NAME_THE_CHECKLIST not in _текст(ответ)


def test_карточка_партнёра_с_кодом_отвечает_его_чеклистом(настройки: Settings) -> None:
    """С названным кодом `checklist_meta` читает чек-лист партнёра как обычно —
    `needs_checklist=False` освобождает от кода, а не от возможности его назвать."""
    ответ = _вызов("checklist_meta", {"checklist": "own"}, настройки)
    assert ответ["result"].get("isError") is not True
    выдача = _текст(ответ)
    assert "own" in выдача and "ge" in выдача


def test_правка_с_кодом_наводится_в_своё_пространство_а_не_в_эталон(настройки: Settings) -> None:
    """Правящий инструмент С кодом наводится в пространство партнёра, а не в
    эталон УК, даже если код совпадает с кодом чек-листа УК (`bizdev`) — два
    разных чек-листа под одним кодом в разных пространствах не одно и то же."""
    import json

    ответ = _вызов("rename_checklist", {"checklist": "own", "name_ru": "Своё имя"}, настройки)
    assert ответ["result"].get("isError") is not True
    выдача = json.loads(_текст(ответ))
    assert выдача["space"] == "ge"
    assert выдача["name_ru"] == "Своё имя"
