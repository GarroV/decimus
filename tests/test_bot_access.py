"""Доступ бота по привязке к учётке (D286), совместимость для действующих (вопрос 2).

Пространство человека — из привязки его Telegram ID к учётке; ID из окружения
и связки `roster.json` — сотрудник УК, но только пока привязки нет.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, TelegramObject, User
from bot_harness import RecordingSession, make_bot

from src.bot.access import (
    BINDING_STALE_MAX,
    SPACE_KEY,
    AccessMiddleware,
    BindingCache,
    is_allowed,
)
from src.bot.roster import Roster
from src.db.bot_links import NEVER_BOUND, Binding, Standing
from src.db.errors import AccessError
from src.domain.tenants import HQ_TENANT

pytestmark = pytest.mark.asyncio


def _msg(user_id: int, text: str = "привет") -> tuple[Message, RecordingSession]:
    bot, session = make_bot()
    message = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Т"),
        text=text,
    ).as_(bot)
    return message, session


def _привязка(tg: int, tenant: str) -> Binding:
    return Binding(
        telegram_id=tg, user_id="u", login="anna", tenant=tenant, bound_at=datetime.now(UTC)
    )


async def _пустить(mw: AccessMiddleware, event: TelegramObject) -> str | None:
    """Пространство, с которым апдейт дошёл до обработчика, — или `None`, если не дошёл."""
    увидено: list[dict[str, Any]] = []

    async def handler(_e: TelegramObject, data: dict[str, Any]) -> None:
        увидено.append(dict(data))

    await mw(handler, event, {})
    return увидено[0][SPACE_KEY] if увидено else None


def _положение(привязка: Binding | None) -> Standing:
    return NEVER_BOUND if привязка is None else Standing.live(привязка)


def _кэш(ответы: dict[int, Binding | None], **настройки: Any) -> BindingCache:
    return BindingCache(standing=lambda tg: _положение(ответы.get(tg)), **настройки)


def _пространство(кэш: BindingCache, tg: int) -> str | None:
    положение = кэш.standing_of(tg)
    return None if положение is None or положение.binding is None else положение.binding.tenant


def _ответы(session: RecordingSession) -> list[str]:
    return [c.text for c in session.calls if isinstance(c, SendMessage)]


async def test_no_user_is_rejected() -> None:
    """Обновление без отправителя (например, служебное) — не пропускаем."""
    assert is_allowed(None, frozenset({111})) is False


async def test_привязанный_работает_в_пространстве_учётки() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({501: _привязка(501, "GE")}), None)
    assert await _пустить(mw, _msg(501)[0]) == "GE"


async def test_незнакомому_бот_молчит() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({}), None)
    message, session = _msg(999)
    assert await _пустить(mw, message) is None
    assert session.calls == [], "постороннему бот ничего не отвечает"


async def test_ссылка_привязывает_незнакомого_и_отвечает_в_тот_же_чат() -> None:
    погашено: list[tuple[str, int]] = []

    def погасить(token: str, *, telegram_id: int) -> Binding | None:
        погашено.append((token, telegram_id))
        return _привязка(telegram_id, "GE")

    mw = AccessMiddleware(frozenset(), _кэш({}), None, redeem=погасить)
    message, session = _msg(501, "/start link-abc")
    assert await _пустить(mw, message) is None, "ссылка обработчику не передаётся"
    assert погашено == [("abc", 501)]
    assert len(_ответы(session)) == 1 and "anna" in _ответы(session)[0]


async def test_негодная_ссылка_не_пускает_и_не_объясняет_причину() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({}), None, redeem=lambda *_a, **_k: None)
    message, session = _msg(501, "/start link-abc")
    assert await _пустить(mw, message) is None
    assert len(_ответы(session)) == 1


async def test_обычный_старт_не_гасит_ссылок() -> None:
    def погасить(*_a: object, **_k: object) -> Binding | None:
        raise AssertionError("обычный /start не ссылка привязки")

    mw = AccessMiddleware(frozenset({111}), _кэш({}), None, redeem=погасить)
    assert await _пустить(mw, _msg(111, "/start")[0]) == HQ_TENANT


async def test_совместимость_пускает_действующих_аудиторов_уК(tmp_path: Path) -> None:
    mw = AccessMiddleware(frozenset({111}), _кэш({}), Roster.load(tmp_path))
    assert await _пустить(mw, _msg(111)[0]) == HQ_TENANT


async def test_связки_по_приглашениям_пускают_как_уК(tmp_path: Path) -> None:
    path = tmp_path / "access" / "roster.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"version": 1, "entries": [{"telegram_id": 222, "username": "apetrov"}]}',
        encoding="utf-8",
    )
    mw = AccessMiddleware(frozenset({111}), _кэш({}), Roster.load(tmp_path))
    assert await _пустить(mw, _msg(222)[0]) == HQ_TENANT


async def test_привязка_главнее_совместимости() -> None:
    """Review Focus 3: ID из окружения, привязанный к учётке партнёра, работает как партнёр."""
    mw = AccessMiddleware(frozenset({111}), _кэш({111: _привязка(111, "GE")}), None)
    assert await _пустить(mw, _msg(111)[0]) == "GE"


async def test_старый_код_тенанта_учётки_читается_как_уК() -> None:
    mw = AccessMiddleware(frozenset(), _кэш({501: _привязка(501, "default")}), None)
    assert await _пустить(mw, _msg(501)[0]) == HQ_TENANT


async def test_отвязка_действует_после_истечения_кэша() -> None:
    сейчас = [datetime(2026, 9, 30, tzinfo=UTC)]
    ответы: dict[int, Binding | None] = {501: _привязка(501, "GE")}
    кэш = _кэш(ответы, ttl=timedelta(seconds=60), now=lambda: сейчас[0])
    assert _пространство(кэш, 501) == "GE"
    ответы[501] = None
    assert _пространство(кэш, 501) == "GE", "в пределах срока кэша — прежний ответ"
    сейчас[0] += timedelta(seconds=61)
    assert _пространство(кэш, 501) is None


async def test_погашенная_ссылка_сбрасывает_кэш() -> None:
    """Партнёр, привязавшийся заново, работает в новом пространстве сразу, без минуты ожидания."""
    ответы: dict[int, Binding | None] = {111: None}
    кэш = _кэш(ответы)

    def погасить(_token: str, *, telegram_id: int) -> Binding | None:
        ответы[telegram_id] = _привязка(telegram_id, "GE")
        return ответы[telegram_id]

    mw = AccessMiddleware(frozenset({111}), кэш, None, redeem=погасить)
    assert await _пустить(mw, _msg(111)[0]) == HQ_TENANT
    await _пустить(mw, _msg(111, "/start link-abc")[0])
    assert await _пустить(mw, _msg(111)[0]) == "GE"


def _кэш_с_отказом(сейчас: list[datetime], живая: list[bool]) -> BindingCache:
    def standing(tg: int) -> Standing:
        if not живая[0]:
            raise AccessError("база недоступна")
        return _положение(_привязка(tg, "GE") if tg == 501 else None)

    return BindingCache(standing=standing, ttl=timedelta(seconds=60), now=lambda: сейчас[0])


async def test_при_коротком_отказе_базы_узнанный_работает_незнакомый_нет() -> None:
    """Вопрос 3: аудитор на точке не остаётся без бота из-за короткого сбоя базы."""
    сейчас = [datetime(2026, 9, 30, tzinfo=UTC)]
    живая = [True]
    кэш = _кэш_с_отказом(сейчас, живая)
    assert _пространство(кэш, 501) == "GE"
    живая[0] = False
    сейчас[0] += BINDING_STALE_MAX - timedelta(seconds=1)
    assert _пространство(кэш, 501) == "GE"
    assert кэш.standing_of(777) is None


async def test_долгий_отказ_базы_прежнего_ответа_не_продлевает() -> None:
    """Ревью #340, п.6: отключённая за время сбоя учётка не работает ботом дальше."""
    сейчас = [datetime(2026, 9, 30, tzinfo=UTC)]
    живая = [True]
    кэш = _кэш_с_отказом(сейчас, живая)
    assert _пространство(кэш, 501) == "GE"
    живая[0] = False
    сейчас[0] += BINDING_STALE_MAX
    assert кэш.standing_of(501) is None
    mw = AccessMiddleware(frozenset({501}), кэш, None)
    assert await _пустить(mw, _msg(501)[0]) is None, "и совместимость не подхватывает"


async def test_при_отказе_базы_совместимость_не_пускает_несверенного() -> None:
    """Был ли этот ID привязан и отвязан — без базы не узнать, поэтому отказ."""
    mw = AccessMiddleware(frozenset({111}), _кэш_с_отказом([datetime.now(UTC)], [False]), None)
    assert await _пустить(mw, _msg(111)[0]) is None


@pytest.mark.parametrize("откуда", ["окружение", "связки"])
async def test_бывшая_привязка_закрывает_путь_совместимости(откуда: str, tmp_path: Path) -> None:
    """Ревью #340, п.5: отвязанный или с отключённой учёткой не пускается как УК."""
    path = tmp_path / "access" / "roster.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"version": 1, "entries": [{"telegram_id": 111, "username": "apetrov"}]}',
        encoding="utf-8",
    )
    разрешённые = frozenset({111}) if откуда == "окружение" else frozenset()
    кэш = BindingCache(standing=lambda _tg: Standing(binding=None, ever_bound=True))
    mw = AccessMiddleware(разрешённые, кэш, Roster.load(tmp_path))
    assert await _пустить(mw, _msg(111)[0]) is None


async def test_каждый_пуск_по_совместимости_пишется_в_журнал(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mw = AccessMiddleware(frozenset({111}), _кэш({}), None)
    with caplog.at_level("WARNING", logger="src.bot.access"):
        assert await _пустить(mw, _msg(111)[0]) == HQ_TENANT
        assert await _пустить(mw, _msg(111)[0]) == HQ_TENANT
    строки = [r.getMessage() for r in caplog.records if "совместимости" in r.getMessage()]
    assert строки == ["путь совместимости: Telegram ID 111 пущен как УК (ALLOWED_TELEGRAM_IDS)"] * 2
