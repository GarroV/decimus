"""Доступ по списку разрешённых Telegram ID.

`docs/forge/blocks/bot.md`: «Отвечает только Telegram ID из списка разрешённых;
чужому не отвечает ничего осмысленного» (T050).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from aiogram.types import Chat, Message, TelegramObject, Update, User

from src.bot.access import AccessMiddleware, is_allowed
from src.bot.invites import StaticInvites, parse_invites
from src.bot.roster import Roster


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="Т")


def test_allowed_id_passes() -> None:
    assert is_allowed(111, frozenset({111, 222})) is True


def test_unknown_id_is_rejected() -> None:
    assert is_allowed(999, frozenset({111, 222})) is False


def test_no_user_is_rejected() -> None:
    """Обновление без отправителя (например, служебное) — не пропускаем."""
    assert is_allowed(None, frozenset({111})) is False


@pytest.mark.asyncio
async def test_middleware_calls_handler_for_allowed_user() -> None:
    middleware = AccessMiddleware(allowed_ids=frozenset({111}))
    called_with: list[TelegramObject] = []

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        called_with.append(event)
        return "handled"

    message = Message(
        message_id=1,
        date=0,  # type: ignore[arg-type]
        chat=Chat(id=111, type="private"),
        from_user=_user(111),
        text="привет",
    )
    result = await middleware(handler, message, {})
    assert result == "handled"
    assert called_with == [message]


@pytest.mark.asyncio
async def test_middleware_drops_update_for_stranger() -> None:
    """Чужому бот не должен отвечать ничего осмысленного: хендлер не зовётся."""
    middleware = AccessMiddleware(allowed_ids=frozenset({111}))
    calls = 0

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        return "handled"

    message = Message(
        message_id=1,
        date=0,  # type: ignore[arg-type]
        chat=Chat(id=999, type="private"),
        from_user=_user(999),
        text="привет",
    )
    result = await middleware(handler, message, {})
    assert result is None
    assert calls == 0


@pytest.mark.asyncio
async def test_middleware_ignores_non_user_events() -> None:
    """Событие без `from_user` (например, канал) — тоже не зовёт хендлер и не падает."""
    middleware = AccessMiddleware(allowed_ids=frozenset({111}))

    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        return "handled"

    update = Update(update_id=1)
    result = await middleware(handler, update, {})
    assert result is None


# --- привод по юзернейму (#230) ---------------------------------------------
#
# Числовой ID нового аудитора неоткуда взять заранее, поэтому стенд называет
# юзернеймы, а ID бот узнаёт при первом контакте и дальше держится за него.


def _named(user_id: int, username: str | None) -> User:
    return User(id=user_id, is_bot=False, first_name="Т", username=username)


def _message_from(user: User) -> Message:
    return Message(
        message_id=1,
        date=0,  # type: ignore[arg-type]
        chat=Chat(id=user.id, type="private"),
        from_user=user,
        text="/start",
    )


async def _passes(middleware: AccessMiddleware, user: User) -> bool:
    async def handler(event: TelegramObject, data: dict[str, Any]) -> str:
        return "handled"

    return await middleware(handler, _message_from(user), {}) == "handled"


def _middleware(
    tmp_path: Path, invites: str, allowed: frozenset[int] = frozenset()
) -> tuple[AccessMiddleware, Roster]:
    roster = Roster.load(tmp_path)
    return (
        AccessMiddleware(
            allowed_ids=allowed,
            invites=StaticInvites(parse_invites(invites)),
            roster=roster,
        ),
        roster,
    )


@pytest.mark.asyncio
async def test_invited_user_is_recognised_on_first_contact(tmp_path: Path) -> None:
    """Клик по «старту» — и человек внутри: ID взят из этого же апдейта."""
    middleware, roster = _middleware(tmp_path, "apetrov:Anna Petrova")

    assert await _passes(middleware, _named(555000111, "apetrov")) is True
    assert roster.knows(555000111) is True
    assert roster.names() == {555000111: "Anna Petrova"}


@pytest.mark.asyncio
async def test_recognised_user_passes_by_id_after_changing_username(tmp_path: Path) -> None:
    """Дальше ключ — число: смена юзернейма доступа не отнимает."""
    middleware, _ = _middleware(tmp_path, "apetrov:Anna Petrova")
    await _passes(middleware, _named(555000111, "apetrov"))

    assert await _passes(middleware, _named(555000111, "anna_new")) is True


@pytest.mark.asyncio
async def test_released_username_does_not_let_a_stranger_in(tmp_path: Path) -> None:
    """Главный тест задачи: приглашение срабатывает ОДИН раз.

    Юзернейм владелец отпускает, и его занимает кто угодно. Если бы
    приглашение работало повторно, посторонний с чужим бывшим юзернеймом
    получил бы отчёты партнёров и историю проверок.
    """
    middleware, _ = _middleware(tmp_path, "apetrov:Anna Petrova")
    await _passes(middleware, _named(555000111, "apetrov"))

    assert await _passes(middleware, _named(999999, "apetrov")) is False


@pytest.mark.asyncio
async def test_invitation_is_matched_case_insensitively(tmp_path: Path) -> None:
    middleware, _ = _middleware(tmp_path, "@Ivanov:Ivan Ivanov")

    assert await _passes(middleware, _named(222, "IVANOV")) is True


@pytest.mark.asyncio
async def test_user_without_username_is_not_let_in(tmp_path: Path) -> None:
    """Юзернейма нет — сверять нечего, и это не повод пускать."""
    middleware, _ = _middleware(tmp_path, "apetrov:Anna Petrova")

    assert await _passes(middleware, _named(333, None)) is False


@pytest.mark.asyncio
async def test_stranger_with_unknown_username_stays_silent(tmp_path: Path) -> None:
    middleware, roster = _middleware(tmp_path, "apetrov:Anna Petrova")

    assert await _passes(middleware, _named(444, "somebody")) is False
    assert roster.knows(444) is False


@pytest.mark.asyncio
async def test_configured_id_still_passes_without_any_invites(tmp_path: Path) -> None:
    """Прежняя дверь не тронута: ID из `ALLOWED_TELEGRAM_IDS` работает как раньше."""
    middleware, _ = _middleware(tmp_path, "", allowed=frozenset({111222333}))

    assert await _passes(middleware, _named(111222333, None)) is True
