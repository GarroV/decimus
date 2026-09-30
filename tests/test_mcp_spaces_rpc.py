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

И ревью Task 2 (controller ruling, круг 1): эталон УК партнёру НЕ чужой — он
виден в его `checklists` (D283, D285). Значит код эталона, названный явно:
- читающему инструменту без требования кода (`checklist_meta`) отвечает
  успехом, а не «не найден» — партнёр читает карточку того, что сам же видит
  в перечне;
- правящему инструменту отвечает явным отказом «эталон правит только УК»
  (`ETALON_READONLY_FOR_PARTNER`, текст дословно из «Глобальных ограничений»
  плана), а не «не найден» — «не найден» остаётся ТОЛЬКО для кода, которого
  нет вообще нигде, включая код чужого ПАРТНЁРА (партнёры друг другу не
  видны, и это неотличимо от выдумки).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, current_version, read_journal, tip_version
from src.mcp.checklist_layout import read_meta
from src.mcp.checklists import create
from src.mcp.config import MIN_TOKEN_LENGTH, Settings
from src.mcp.rpc import ETALON_READONLY_FOR_PARTNER, NAME_THE_CHECKLIST, handle
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


def _чек_лист_store(настройки: Settings, *, space: str, code: str) -> Store:
    assert настройки.checklist_store is not None and настройки.data_dir is not None
    return Store(root=настройки.checklist_store, live=настройки.data_dir, space=space, code=code)


def test_правка_партнёра_наведена_на_его_пространство(настройки: Settings) -> None:
    store = _checklist_for(настройки, ПАРТНЁР)
    assert store is not None and store.space == "ge"


def test_исходник_эталона_читается_из_пространства_уК(настройки: Settings) -> None:
    store = _checklist_source_for(настройки, ПАРТНЁР)
    assert store is not None and store.space == "hq"


def test_правящий_инструмент_без_кода_не_уходит_в_эталон(настройки: Settings) -> None:
    """Review Focus 4."""
    эталон = _чек_лист_store(настройки, space="hq", code="bizdev")
    было = len(read_journal(эталон))
    ответ = _вызов("set_checklist_state", {"state": "retired"}, настройки)
    assert ответ["result"].get("isError") is True
    assert NAME_THE_CHECKLIST in _текст(ответ)
    assert len(read_journal(эталон)) == было


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
    """Правящий инструмент С СОБСТВЕННЫМ кодом партнёра наводится в его
    пространство, а не куда-то ещё: `_aimed` не путает «код есть в своём
    пространстве» ни с эталоном, ни с применённым к проду. (Случай, где код
    партнёра совпадает с кодом эталона, — отдельные тесты ниже: «правка»
    там не проходит вовсе, она отказывает `ETALON_READONLY_FOR_PARTNER`.)"""
    ответ = _вызов("rename_checklist", {"checklist": "own", "name_ru": "Своё имя"}, настройки)
    assert ответ["result"].get("isError") is not True
    выдача = json.loads(_текст(ответ))
    assert выдача["space"] == "ge"
    assert выдача["name_ru"] == "Своё имя"


# --- controller ruling: эталон партнёру виден (D283/D285), не «чужое по адресу» ---


def test_карточка_партнёра_с_кодом_эталона_отвечает_успехом(настройки: Settings) -> None:
    """`checklist_meta` — чтение. Партнёр видит строку эталона в `checklists`
    (D283, D285), значит вправе прочитать и его карточку явным кодом — это
    не «чужое по прямому адресу», это видимое чужое с попыткой ЧТЕНИЯ."""
    ответ = _вызов("checklist_meta", {"checklist": "bizdev"}, настройки)
    assert ответ["result"].get("isError") is not True
    выдача = json.loads(_текст(ответ))
    assert выдача["space"] == "hq"
    assert выдача["checklist"] == "bizdev"
    # Отвечает от имени СПРОСИВШЕГО — это по-прежнему ответ партнёру, а не УК.
    assert выдача["tenant"] == ПАРТНЁР


def test_запись_партнёра_в_эталон_это_явный_отказ_а_не_не_найден(настройки: Settings) -> None:
    """Важно (ревью Task 2): правящий инструмент с кодом эталона получает
    ИМЕННО текст `ETALON_READONLY_FOR_PARTNER`, а не подстроку «не найден» —
    а `hq/bizdev` после отказа не тронут ни журналом, ни карточкой."""
    эталон = _чек_лист_store(настройки, space="hq", code="bizdev")
    журнал_до = read_journal(эталон)
    карточка_до = read_meta(эталон)
    издание_до = tip_version(эталон)

    ответ = _вызов("set_checklist_state", {"checklist": "bizdev", "state": "retired"}, настройки)

    assert ответ["result"].get("isError") is True
    assert _текст(ответ) == ETALON_READONLY_FOR_PARTNER.format(код="bizdev")
    assert read_journal(эталон) == журнал_до
    assert read_meta(эталон) == карточка_до
    assert tip_version(эталон) == издание_до


def test_переименование_эталона_партнёром_это_тот_же_отказ_и_hq_не_тронут(
    настройки: Settings,
) -> None:
    """Тот же заслон на ВТОРОМ правящем инструменте (ревью Task 2, Important
    №1: «заслон держится только на одном инструменте» — здесь их уже два)."""
    эталон = _чек_лист_store(настройки, space="hq", code="bizdev")
    журнал_до = read_journal(эталон)
    карточка_до = read_meta(эталон)

    ответ = _вызов("rename_checklist", {"checklist": "bizdev", "name_ru": "Захват"}, настройки)

    assert ответ["result"].get("isError") is True
    assert _текст(ответ) == ETALON_READONLY_FOR_PARTNER.format(код="bizdev")
    assert read_journal(эталон) == журнал_до
    assert read_meta(эталон) == карточка_до


def test_партнёр_на_код_чужого_партнёра_тот_же_ответ_что_на_несуществующий(
    настройки: Settings,
) -> None:
    """«Не найден» остаётся тем же кодом и текстом, что у выдуманного кода
    (constraints.md, Global Constraints): партнёры друг другу не видны, и
    код партнёра AM («rnd») для партнёра GE ничем не отличим от фантазии."""
    чужой_партнёр = _чек_лист_store(настройки, space="am", code="rnd")
    карточка_до = read_meta(чужой_партнёр)

    чужой = _вызов("rename_checklist", {"checklist": "rnd", "name_ru": "x"}, настройки)
    выдуманный = _вызов("rename_checklist", {"checklist": "nope-9000", "name_ru": "x"}, настройки)

    шаблон = "Чек-листа «{код}» в пространстве «ge» нет. Перечень отдаёт checklists"
    assert чужой["result"].get("isError") is True
    assert выдуманный["result"].get("isError") is True
    assert _текст(чужой) == шаблон.format(код="rnd")
    assert _текст(выдуманный) == шаблон.format(код="nope-9000")
    # AM попытку GE тоже не почувствовал: её чек-лист не найден, а не тронут.
    assert read_meta(чужой_партнёр) == карточка_до
