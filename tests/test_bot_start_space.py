"""Волна 1 (#340): бот ведёт проверку в пространстве того, кто её начал."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram import Dispatcher
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot, text_message
from test_bot_start_router import settings

from src.bot import unit_pick
from src.bot.access import BindingCache
from src.bot.app import build_dispatcher
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.db.bot_links import Binding
from src.domain import get_state, start_inspection
from src.domain.tenants import HQ_TENANT

pytestmark = pytest.mark.asyncio


def _партнёр() -> BindingCache:
    def resolve(tg: int) -> Binding | None:
        if tg != AUDITOR_ID:
            return None
        return Binding(tg, "u", "ge-auditor", "GE", datetime.now(UTC))

    return BindingCache(resolve=resolve)


def _диспетчер() -> Dispatcher:
    return build_dispatcher(replace(settings(), allowed_ids=frozenset()), bindings=_партнёр())


async def test_справочник_сверяется_в_пространстве_аудитора(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    спросили: list[str] = []

    def сверка(typed: str, *, tenant: str) -> unit_pick.UnitMatch:
        спросили.append(tenant)
        return unit_pick.UnitMatch(name="Batumi-1", suggestions=(), checked=True)

    from src.bot.routers import start as start_router

    monkeypatch.setattr(start_router, "match_unit", сверка)
    bot, _session = make_bot()
    dp = _диспетчер()
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Батуми 1"))
    assert спросили == ["GE"]


async def test_партнёр_не_заводит_пиццерию() -> None:
    assert unit_pick.may_add_units("GE") is False
    assert unit_pick.may_add_units(HQ_TENANT) is True
    assert unit_pick.may_add_units("default") is True


async def test_чужая_проверка_в_чате_не_дописывается(domain_env: Path) -> None:
    """Review Focus 6 на живом диспетчере."""
    start_inspection(CHAT_ID, unit="Тестовая", kind="planned", report_lang="ru", tenant=HQ_TENANT)
    bot, session = make_bot()
    await feed(_диспетчер(), bot, text_message("холодильник грязный"))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.tenant == HQ_TENANT and not состояние.findings
    assert "другом пространстве" in session.last_text


async def test_проверка_партнёра_начинается_в_его_пространстве(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.bot.routers import start as start_router

    monkeypatch.setattr(
        start_router,
        "match_unit",
        lambda _t, **_k: unit_pick.UnitMatch(name="Batumi-1", suggestions=(), checked=True),
    )
    bot, _session = make_bot()
    dp = _диспетчер()
    await feed(dp, bot, text_message("/start"))
    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Батуми 1"))
    await feed(dp, bot, callback_query("start:kind:planned"))
    await feed(dp, bot, callback_query("start:lang:ru"))
    состояние = get_state(CHAT_ID)
    assert состояние is not None and состояние.tenant == "GE"
