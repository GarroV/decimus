"""Каждая дверь ставит пространство обращения к базе (аудит 12.10, F-037).

Политики роли приложения (`0062`) без пространства отказывают ошибкой, поэтому
дверь, которая его не поставила, сломалась бы на проде на первом же запросе.
Здесь каждая дверь проверяется без базы: что видит код за ней и что после неё
пространство снято.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiogram.types import TelegramObject
from flask import Flask
from test_bot_access import _msg, _кэш, _привязка
from web_harness import войти, подменить_двери, собрать

from src.bot import agg_loader, maps_loader, photo_backfill
from src.bot.access import AccessMiddleware
from src.db.space import SYSTEM_SPACE, current_space
from src.mcp import rpc
from src.web import swarm_api, walk


def test_веб_ставит_пространство_вошедшего_и_снимает_после(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подменить_двери(monkeypatch, tenant="GE")
    app: Flask = собрать(tenant="HQ")
    увидено: list[str | None] = []
    app.before_request(lambda: увидено.append(current_space()))
    with app.test_client() as client:
        войти(client)
        client.get("/")
    assert увидено[-1] == "GE", f"За заслоном входа пространство {увидено[-1]!r}, а не GE"
    assert current_space() is None, "Пространство вошедшего пережило запрос"


@pytest.mark.asyncio
async def test_бот_ставит_пространство_человека_и_в_потоках() -> None:
    mw = AccessMiddleware(_кэш({501: _привязка(501, "GE")}), None)
    увидено: list[str | None] = []

    async def handler(_e: TelegramObject, _data: dict[str, Any]) -> None:
        увидено.append(current_space())
        увидено.append(await asyncio.to_thread(current_space))

    await mw(handler, _msg(501)[0], {})
    assert увидено == ["GE", "GE"]
    assert current_space() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("модуль", "имя", "аргументы"),
    [
        (maps_loader, "_load_forever", ()),
        (agg_loader, "_load_forever", ()),
        (photo_backfill, "_backfill_forever", (object(),)),
    ],
)
async def test_служебные_задачи_бота_идут_служебным_пространством(
    monkeypatch: pytest.MonkeyPatch, модуль: Any, имя: str, аргументы: tuple[Any, ...]
) -> None:
    увидено: list[str | None] = []

    async def тело(*_a: Any) -> None:
        увидено.append(current_space())

    monkeypatch.setattr(модуль, имя, тело)
    публичное = имя.lstrip("_")
    await getattr(модуль, публичное)(*аргументы)
    assert увидено == [SYSTEM_SPACE]


def test_MCP_вызов_инструмента_идёт_от_имени_пространства_токена(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    увидено: list[str | None] = []

    def _call_tool(*_a: Any, **_k: Any) -> dict[str, Any]:
        увидено.append(current_space())
        return {"content": []}

    monkeypatch.setattr(rpc, "_call_tool", _call_tool)
    rpc.handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "x"}},
        tenant="AM",
    )
    assert увидено == ["AM"]
    assert current_space() is None


def test_API_для_сервисов_идёт_служебным_пространством(monkeypatch: pytest.MonkeyPatch) -> None:
    увидено: list[str | None] = []

    def _serve_as_system(*_a: Any) -> tuple[Any, int]:
        увидено.append(current_space())
        return None, 200

    monkeypatch.setattr(swarm_api, "_serve_as_system", _serve_as_system)
    swarm_api._serve(None, "scope", lambda _c: {})  # type: ignore[arg-type]
    assert увидено == [SYSTEM_SPACE]


def test_обход_ставит_пространство_и_снимает_на_выходе() -> None:
    app = Flask(__name__)
    with app.test_request_context():
        walk._act_for("GE")
        walk._act_for("GE")  # повторное опознание в том же запросе — не ошибка
        assert current_space() == "GE"
        walk._leave_space(None)
        assert current_space() is None
