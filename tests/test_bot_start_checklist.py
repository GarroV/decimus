"""Волна 3: выбор чек-листа на старте проверки в боте.

Один открыт — бот не спрашивает (как до волны 3). Несколько — кнопки. Ни
одного — прямо говорит и дальше не идёт. Кнопка чек-листа, который тем
временем закрыли, не подменяется соседним молча.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from bot_harness import CHAT_ID, callback_query, feed, make_bot, text_message
from test_bot_start_router import settings

from src.bot.app import build_dispatcher
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.domain import get_state
from src.mcp.checklist import Store, apply_change, current_version, publish
from src.mcp.checklists import create, set_bot_access, set_state

pytestmark = pytest.mark.asyncio
АРЕНДАТОР = "укашка"


@pytest.fixture
def хранилище(domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    import os

    методика = tmp_path / "методика"
    shutil.copytree(os.environ["AUDIT_DATA_DIR"], методика)
    monkeypatch.setenv("AUDIT_DATA_DIR", str(методика))
    store = Store(root=tmp_path / "хранилище", live=методика)
    current_version(store)
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(store.root))
    return store


def _открыть_второй(store: Store) -> Store:
    rnd = replace(store, code="rnd")
    create(rnd, tenant=АРЕНДАТОР, name_ru="Аудит РНД", name_en="RnD audit", today=date(2026, 9, 28))
    правка = apply_change(
        rnd,
        tenant=АРЕНДАТОР,
        tool="add_checklist_item",
        command="add",
        options={
            "id": "RND01",
            "process": "Проба",
            "question-ru": "Тесто соответствует техкарте",
            "levels": "D1",
            "zones": "all",
            "days": 5,
            "criteria": "D1: проба",
        },
        today=date(2026, 9, 28),
    )
    assert правка.accepted and правка.version is not None, правка
    publish(rnd, tenant=АРЕНДАТОР, version=правка.version)
    set_state(rnd, tenant=АРЕНДАТОР, state="active")
    set_bot_access(rnd, tenant=АРЕНДАТОР, on=True)
    return rnd


async def _до_выбора() -> tuple[object, object, object]:
    bot, session = make_bot()
    dp = build_dispatcher(settings())
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    return dp, bot, session


async def test_один_открытый_бот_не_спрашивает(хранилище: Store) -> None:
    _, _, session = await _до_выбора()

    assert "пиццерии" in session.last_text.lower()  # type: ignore[attr-defined]


async def test_несколько_открытых_кнопки_и_проверка_по_выбранному(хранилище: Store) -> None:
    _открыть_второй(хранилище)
    dp, bot, session = await _до_выбора()

    assert set(session.keyboard_data()) == {"start:cl:bizdev", "start:cl:rnd"}  # type: ignore[attr-defined]

    await feed(dp, bot, callback_query("start:cl:rnd"))
    assert "пиццерии" in session.last_text.lower()  # type: ignore[attr-defined]
    await feed(dp, bot, text_message("Белград 2"))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))

    проверка = get_state(CHAT_ID)
    assert проверка is not None and проверка.checklist_code == "rnd"


async def test_ни_одного_открытого_бот_прямо_говорит(хранилище: Store) -> None:
    set_bot_access(хранилище, tenant=АРЕНДАТОР, on=False)

    _, _, session = await _до_выбора()

    assert "не по чему" in session.last_text  # type: ignore[attr-defined]
    assert not any("пиццерии" in т.lower() for т in session.texts)  # type: ignore[attr-defined]


async def test_кнопка_закрытого_чек_листа_показывает_свежий_список(хранилище: Store) -> None:
    rnd = _открыть_второй(хранилище)
    dp, bot, session = await _до_выбора()
    set_bot_access(rnd, tenant=АРЕНДАТОР, on=False)

    await feed(dp, bot, callback_query("start:cl:rnd"))

    тексты = " ".join(session.texts)  # type: ignore[attr-defined]
    assert "закрыли" in тексты
    assert get_state(CHAT_ID) is None
