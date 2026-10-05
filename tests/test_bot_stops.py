"""Отказ, который останавливает мастер, оставляет след с кодом шага (#436).

До задачи бот отказывал аудитору молча для всех, кроме него самого: с 24.09 по
29.09 отказ «пиццерии нет в справочнике» не попал ни в журнал, ни в счётчик, и
сколько людей так упёрлось, посчитать нечем. Здесь проверяется ЗАПУСКОМ через
настоящий диспетчер: человек упирается в отказ — в журнале строка с шагом,
причиной и Telegram ID, но без имени, а в счётчике — строка для `/stops`.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiogram import Bot
from aiogram.types import Message
from bot_harness import (
    AUDITOR_ID,
    CHAT_ID,
    callback_query,
    feed,
    make_bot,
    text_message,
)
from conftest import requires_db

from src import db
from src.bot import stops
from src.bot.app import build_dispatcher
from src.bot.config import BotSettings
from src.bot.keyboards import NEW_INSPECTION_CALLBACK
from src.bot.texts import t
from src.bot.unit_pick import UnitMatch

pytestmark = pytest.mark.asyncio

ИМЯ = "Владимир Гарро"


def settings(owner: int | None = None) -> BotSettings:
    return BotSettings(
        token="unused-in-tests",
        allowed_ids=frozenset({AUDITOR_ID}),
        mode="polling",
        mcp_owner_id=owner,
    )


def строки_счётчика(state: Path) -> list[dict[str, object]]:
    path = state / stops.STOPS_FILE_NAME
    if not path.exists():
        return []
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines()]


def отказы_в_журнале(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("отказ мастера")]


async def test_отказ_на_шаге_названия_пишется_с_кодом_шага_и_без_имени(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Название без номера — мастер стоит. В журнале шаг, причина, ID; имени нет."""
    monkeypatch.setattr(
        "src.bot.routers.start.match_unit",
        lambda name, *, tenant: UnitMatch(name=name, suggestions=(), checked=True),
    )
    bot, session = make_bot()
    dp = build_dispatcher(settings())
    caplog.set_level(logging.WARNING, logger="src.bot.stops")

    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Белград", full_name=ИМЯ))

    assert session.last_text == t("start.unit_need_number", "ru", typed="Белград")
    журнал = отказы_в_журнале(caplog)
    assert журнал, "отказ мастера не оставил строки в журнале"
    assert "шаг=start.unit" in журнал[-1]
    assert "причина=start.unit_need_number" in журнал[-1]
    assert f"telegram_id={CHAT_ID}" in журнал[-1]
    assert all("Гарро" not in строка and "Владимир" not in строка for строка in журнал)
    счётчик = строки_счётчика(domain_env)
    assert [(r["step"], r["reason"], r["telegram_id"]) for r in счётчик] == [
        ("start.unit", "start.unit_need_number", CHAT_ID)
    ]


async def test_принятое_название_отказом_не_считается(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Обратная сторона: шаг, который прошёл, счётчик не пачкает."""
    monkeypatch.setattr(
        "src.bot.routers.start.match_unit",
        lambda name, *, tenant: UnitMatch(name=name, suggestions=(), checked=True),
    )
    bot, _ = make_bot()
    dp = build_dispatcher(settings())
    caplog.set_level(logging.WARNING, logger="src.bot.stops")

    await feed(dp, bot, callback_query(NEW_INSPECTION_CALLBACK))
    await feed(dp, bot, text_message("Белград 2"))

    assert not отказы_в_журнале(caplog)
    assert строки_счётчика(domain_env) == []


async def test_отказ_сторожа_точки_на_сливе_считается_шагом_finish_archive(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#482 и #436 вместе: отказ точки на финише — тоже отказ, и он посчитан."""
    from src.bot.routers import finish

    def слив(chat_id: int) -> str:
        raise db.UnitRefusedError("точки нет", unit="Yerevan-1")

    monkeypatch.setattr(db, "push_inspection", слив, raising=False)
    bot, session = make_bot()
    caplog.set_level(logging.WARNING, logger="src.bot.stops")

    await finish.archive(_сообщение(bot), CHAT_ID, {}, "ru", allow_missing=True)

    assert session.last_text == t("finish.unit_refused", "ru", unit="Yerevan-1")
    assert [(r["step"], r["reason"]) for r in строки_счётчика(domain_env)] == [
        ("finish.archive", "finish.unit_refused")
    ]


def _сообщение(bot: Bot) -> Message:
    """Сообщение, привязанное к боту: `archive` отвечает в него, как в бою."""
    return text_message("служебное").as_(bot)


async def test_счётчик_считает_людей_и_отрезает_период(tmp_path: Path) -> None:
    """Три отказа двоим за неделю и один старый: старый не в счёт, людей двое."""
    сейчас = datetime.now(UTC)
    path = tmp_path / stops.STOPS_FILE_NAME
    строки = [
        (сейчас - timedelta(days=30), "start.unit", "start.unit_need_number", 1),
        (сейчас - timedelta(days=1), "start.unit", "start.unit_need_number", 1),
        (сейчас - timedelta(days=1), "start.unit", "start.unit_need_number", 2),
        (сейчас - timedelta(hours=1), "start.unit", "start.unit_need_number", 1),
        (сейчас - timedelta(hours=1), "finish.archive", "finish.unit_refused", 2),
    ]
    path.write_text(
        "\n".join(
            json.dumps({"at": at.isoformat(), "step": s, "reason": r, "telegram_id": who})
            for at, s, r, who in строки
        )
        + "\nне json\n",
        encoding="utf-8",
    )

    итог = stops.count_stops(сейчас - timedelta(days=7), path=path)

    assert итог == [
        stops.StopCount("start.unit", "start.unit_need_number", times=3, people=2),
        stops.StopCount("finish.archive", "finish.unit_refused", times=1, people=1),
    ]


@requires_db
async def test_stops_показывает_счётчик_админу(domain_env: Path, db_env: str) -> None:
    """Владелец открывает счётчик сам: `/stops` — строка на шаг, раз и люди."""
    stops.note_stop(1, step="start.unit", reason="start.unit_need_number")
    stops.note_stop(2, step="start.unit", reason="start.unit_need_number")
    bot, session = make_bot()
    dp = build_dispatcher(settings(owner=AUDITOR_ID))

    await feed(dp, bot, text_message("/stops"))

    assert "start.unit" in session.last_text
    assert "start.unit_need_number" in session.last_text
    assert (
        t("stops.line", "ru", step="start.unit", reason="start.unit_need_number", times=2, people=2)
        in session.last_text
    )


async def test_stops_без_настроенного_круга_не_показывает_счётчик(domain_env: Path) -> None:
    """Круг админов не настроен — счётчик никому, ответ тот же, что у `/mcp`."""
    stops.note_stop(1, step="start.unit", reason="start.unit_need_number")
    bot, session = make_bot()
    dp = build_dispatcher(settings(owner=None))

    await feed(dp, bot, text_message("/stops"))

    assert session.last_text == t("mcp.circle_unset", "ru")
    assert "start.unit" not in session.last_text
