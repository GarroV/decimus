"""Волна 3: доступ чек-листов в бот — флаг у нескольких, заслоны, наследование.

Ядро — наследование карточек до волны 3. Хранилище прода не знает ключа
`in_bot`, и первое открытие после выката обязано показать в боте ровно тот
чек-лист, по которому проверки шли вчера. Второй риск — первое же включение
второго чек-листа не должно молча снять с бота первый.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from mcp_checklist_harness import build_methodology

from src.mcp.checklist import Store, apply_change, current_version, publish, read_journal
from src.mcp.checklist_layout import META_FILE, read_meta
from src.mcp.checklists import (
    BOT_BLOCK_DRAFT,
    BOT_BLOCK_EMPTY,
    BOT_BLOCK_RETIRED,
    BOT_BLOCK_UNPUBLISHED,
    bot_block,
    create,
    overview,
    set_bot_access,
    set_state,
)
from src.mcp.errors import ChecklistError

АРЕНДАТОР = "укашка"
СЕГОДНЯ = date(2026, 9, 28)


@pytest.fixture
def хранилище(tmp_path: Path) -> Store:
    store = Store(root=tmp_path / "хранилище", live=build_methodology(tmp_path / "методика"))
    current_version(store)
    return store


def _заведён(
    хранилище: Store, code: str = "rnd", *, пункт: bool = True, опубликован: bool = True
) -> Store:
    свой = replace(хранилище, code=code)
    create(свой, tenant=АРЕНДАТОР, name_ru=f"Аудит {code}", name_en=code, today=СЕГОДНЯ)
    if not пункт:
        return свой
    правка = apply_change(
        свой,
        tenant=АРЕНДАТОР,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "RND01",
            "process": "Проба",
            "question-ru": "Проба пера",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=СЕГОДНЯ,
    )
    assert правка.accepted and правка.version is not None
    if опубликован:
        publish(свой, tenant=АРЕНДАТОР, version=правка.version)
    return свой


def _в_боте(хранилище: Store) -> set[str]:
    return {o.code for o in overview(хранилище) if o.in_bot}


def test_карточка_без_флага_наследует_указатель_прода(хранилище: Store) -> None:
    _заведён(хранилище)
    карточка = json.loads((хранилище.home / META_FILE).read_text(encoding="utf-8"))
    assert "in_bot" not in карточка, "стартовое хранилище обязано выглядеть как прод до волны 3"

    assert _в_боте(хранилище) == {"bizdev"}


def test_второй_открывается_рядом_и_не_снимает_первый(хранилище: Store) -> None:
    свой = _заведён(хранилище)
    set_state(свой, tenant=АРЕНДАТОР, state="active")

    set_bot_access(свой, tenant=АРЕНДАТОР, on=True, by="web:мария")

    assert _в_боте(хранилище) == {"bizdev", "rnd"}
    первый = read_meta(хранилище)
    assert первый is not None and первый.in_bot is True, "наследованное обязано записаться явно"


def test_закрыть_можно_и_последний(хранилище: Store) -> None:
    set_bot_access(хранилище, tenant=АРЕНДАТОР, on=False)

    assert _в_боте(хранилище) == set()


def test_решение_записано_журналом_с_автором(хранилище: Store) -> None:
    set_bot_access(хранилище, tenant=АРЕНДАТОР, on=False, by="web:мария")

    последнее = read_journal(хранилище)[-1]
    assert последнее["tool"] == "set_bot_access"
    assert "web:мария" in str(последнее["note"])


@pytest.mark.parametrize(
    ("готовим", "причина"),
    [
        ("черновик", BOT_BLOCK_DRAFT),
        ("снят", BOT_BLOCK_RETIRED),
        ("не опубликован", BOT_BLOCK_UNPUBLISHED),
        ("пустой", BOT_BLOCK_EMPTY),
    ],
)
def test_негодный_в_бот_не_открывается(хранилище: Store, готовим: str, причина: str) -> None:
    if готовим == "черновик":
        свой = _заведён(хранилище)
    elif готовим == "снят":
        свой = _заведён(хранилище)
        set_state(свой, tenant=АРЕНДАТОР, state="retired")
    elif готовим == "не опубликован":
        свой = _заведён(хранилище, опубликован=False)
        set_state(свой, tenant=АРЕНДАТОР, state="active")
    else:
        свой = _заведён(хранилище, пункт=False)
        set_state(свой, tenant=АРЕНДАТОР, state="active")

    assert bot_block(свой) == причина
    with pytest.raises(ChecklistError):
        set_bot_access(свой, tenant=АРЕНДАТОР, on=True)
    карточка = read_meta(свой)
    assert карточка is not None and карточка.in_bot is not True
    assert "rnd" not in _в_боте(хранилище)


def test_снятый_с_флагом_в_боте_не_виден(хранилище: Store) -> None:
    """Флаг — намерение, «в работе» — годность: снятый в бот не попадает."""
    свой = _заведён(хранилище)
    set_state(свой, tenant=АРЕНДАТОР, state="active")
    set_bot_access(свой, tenant=АРЕНДАТОР, on=True)

    set_state(свой, tenant=АРЕНДАТОР, state="retired")

    assert "rnd" not in _в_боте(хранилище)


def test_смена_названия_и_состояния_не_теряет_флаг(хранилище: Store) -> None:
    from src.mcp.checklists import rename

    свой = _заведён(хранилище)
    set_state(свой, tenant=АРЕНДАТОР, state="active")
    set_bot_access(свой, tenant=АРЕНДАТОР, on=True)

    rename(свой, tenant=АРЕНДАТОР, name_ru="Аудит РНД-2", name_en="RnD-2")

    карточка = read_meta(свой)
    assert карточка is not None and карточка.in_bot is True
