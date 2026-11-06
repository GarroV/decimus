"""#1300: запись «юзернейм → учётка» одноразовая и уходит после привязки; файл — вместе с ней."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from aiogram.types import Chat, Message, TelegramObject, User
from bot_harness import make_bot

from src.bot.access import AccessMiddleware, BindingCache
from src.bot.pending_links import PendingUsernames
from src.db.bot_links import NEVER_BOUND, Binding


def _файл(tmp_path: Path, записи: dict[str, str]) -> Path:
    путь = tmp_path / "pending_usernames.json"
    путь.write_text(json.dumps(записи), encoding="utf-8")
    return путь


def test_consume_снимает_только_свою_запись(tmp_path: Path) -> None:
    путь = _файл(tmp_path, {"@Anna": "anna", "boris": "boris"})
    ожидающие = PendingUsernames(путь)

    ожидающие.consume("anna")

    assert ожидающие.login_for("anna") is None, "запись не снята — привязка повторится"
    assert ожидающие.login_for("@Boris") == "boris", "чужая запись пропала"


def test_consume_последней_записи_удаляет_файл(tmp_path: Path) -> None:
    путь = _файл(tmp_path, {"anna": "anna"})

    PendingUsernames(путь).consume("@ANNA")

    assert not путь.exists(), "после трёх человек файл должен уйти сам"


def test_consume_чужого_юзернейма_и_без_файла_ничего_не_ломает(tmp_path: Path) -> None:
    путь = _файл(tmp_path, {"anna": "anna"})
    ожидающие = PendingUsernames(путь)

    ожидающие.consume("nobody")
    ожидающие.consume(None)
    PendingUsernames(tmp_path / "нет.json").consume("anna")

    assert ожидающие.login_for("anna") == "anna"


def test_битый_файл_не_трогается(tmp_path: Path) -> None:
    путь = tmp_path / "pending_usernames.json"
    путь.write_text("{не json", encoding="utf-8")

    PendingUsernames(путь).consume("anna")

    assert путь.read_text(encoding="utf-8") == "{не json"


def _сообщение(user_id: int, username: str) -> Message:
    бот, _ = make_bot()
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Т", username=username),
        text="/start",
    ).as_(бот)


async def _пустить(mw: AccessMiddleware, событие: TelegramObject) -> bool:
    дошло: list[dict[str, Any]] = []

    async def обработчик(_e: TelegramObject, data: dict[str, Any]) -> None:
        дошло.append(data)

    await mw(обработчик, событие, {})
    return bool(дошло)


def _привязка(tg: int) -> Binding:
    return Binding(
        telegram_id=tg,
        user_id="u",
        login="anna",
        tenant="HQ",
        bound_at=datetime.now(UTC),
        role="auditor",
    )


@pytest.mark.asyncio
async def test_успешная_привязка_по_юзернейму_снимает_запись(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    путь = _файл(tmp_path, {"anna": "anna"})
    привязывали: list[str] = []

    def привязать(login: str, *, telegram_id: int) -> Binding:
        привязывали.append(login)
        return _привязка(telegram_id)

    monkeypatch.setattr("src.bot.access.bot_links.bind_by_login", привязать)
    mw = AccessMiddleware(
        BindingCache(standing=lambda _tg: NEVER_BOUND), None, pending=PendingUsernames(путь)
    )

    await _пустить(mw, _сообщение(501, "Anna"))

    assert привязывали == ["anna"]
    assert not путь.exists(), "запись осталась после привязки — она не одноразовая"


@pytest.mark.asyncio
async def test_неудачная_привязка_запись_не_снимает(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    путь = _файл(tmp_path, {"anna": "anna"})
    monkeypatch.setattr("src.bot.access.bot_links.bind_by_login", lambda *_a, **_k: None)
    mw = AccessMiddleware(
        BindingCache(standing=lambda _tg: NEVER_BOUND),
        None,
        pending=PendingUsernames(путь),
    )

    await _пустить(mw, _сообщение(501, "anna"))

    assert PendingUsernames(путь).login_for("anna") == "anna"
