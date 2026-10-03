"""Волна 1 (#340): бот ведёт проверку в пространстве того, кто её начал."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram import Dispatcher
from bot_harness import AUDITOR_ID, CHAT_ID, callback_query, feed, make_bot, text_message
from conftest import requires_db
from db_harness import привязать_страну, точка_справочника
from test_bot_start_router import settings

from src.bot import unit_pick
from src.bot.access import BindingCache
from src.bot.app import build_dispatcher
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.db.bot_links import NEVER_BOUND, Binding, Standing
from src.domain import get_state, start_inspection
from src.domain.tenants import HQ_TENANT

pytestmark = pytest.mark.asyncio


def _партнёр() -> BindingCache:
    def standing(tg: int) -> Standing:
        if tg != AUDITOR_ID:
            return NEVER_BOUND
        return Standing.live(Binding(tg, "u", "ge-auditor", "GE", datetime.now(UTC)))

    return BindingCache(standing=standing)


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


@requires_db
async def test_партнёру_чужая_страна_и_вне_справочника_отвечают_одним_текстом(
    domain_env: Path, pg_dsn: str, db_env: str
) -> None:
    """Ревью #340, п.10: ответ не подтверждает, что пиццерия в сети есть.

    Справочник настоящий: Batumi-1 (GE) и Yerevan-1 (AM), партнёр — GE.
    """
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    точка_справочника("Yerevan-1", country="AM", city="Yerevan")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    ответы = []
    for точка in ("Yerevan-1", "Yerevan-99"):
        bot, session = make_bot()
        dp = _диспетчер()
        await feed(dp, bot, text_message("/start"))
        await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
        await feed(dp, bot, text_message(точка))
        ответы.append(session.last_text.replace(точка, "…"))
        assert get_state(CHAT_ID) is None
    assert ответы[0] == ответы[1]
    assert "только" in ответы[0], ответы[0]
