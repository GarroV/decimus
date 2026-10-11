"""Кто работает ботом и в каком пространстве (D286, волна 1 — #340).

Незнакомому отправителю бот не отвечает ничего осмысленного (принцип
безопасности проекта, `docs/furca/constitution.md`): апдейт от него до хендлера
не доходит вовсе, а не получает отдельное сообщение об отказе — иначе бот сам
подтверждает постороннему, что он существует и что этот ID неверный.

Дверей три, и порядок между ними жёсткий:

1. `/start link-<токен>` — человек открыл ссылку привязки, выпущенную ему в вебе
   (`src.db.bot_links`). Ссылка гасится, Telegram ID привязывается к учётке.
   Это единственный ответ незнакомому: у него уже есть ссылка на бота, и
   молчание на просроченную ссылку выглядит как поломка. Ответ один на все
   причины отказа и не подсказывает, чем отказ вызван.
2. Живая привязка — пространство УЧЁТКИ, к которой привязан Telegram ID.
3. Совместимость до снятия (вопрос 2): `ALLOWED_TELEGRAM_IDS` и связки
   `roster.json`, собранные до D286, — сотрудник УК. Только если привязки НЕ
   БЫЛО НИКОГДА: привязанный к учётке партнёра работает как партнёр, даже если
   его ID есть в окружении, а отвязанный или с отключённой учёткой не пускается
   вовсе (ревью #340, п.5). Каждый пуск по совместимости — строка в журнале.

База привязок молчит — последний ответ годен не дольше `BINDING_STALE_MAX`,
дальше отказ всем, кого нечем сверить (п.6).

Пространство человека кладётся в `data[SPACE_KEY]`; обработчик получает его
параметром `space`. Второй заслон, `ChatSpaceMiddleware`, не пускает апдейт к
проверке чата, начатой в другом пространстве.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject

from src.db import bot_links
from src.db.bot_links import LINK_PREFIX, NEVER_BOUND, Binding, Standing
from src.db.errors import DbError
from src.domain.errors import DomainError
from src.domain.tenants import HQ_TENANT, canonical_tenant

from .inspection import read_inspection
from .lang import chat_ui_lang
from .roster import Roster
from .texts import t

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

#: Ключ пространства человека в `data` апдейта.
SPACE_KEY = "space"
#: Сколько живёт ответ «чья привязка»: не ходить в базу на каждый кадр альбома.
#: Столько же после отвязки в вебе бот ещё пускает человека в прежнее пространство.
BINDING_TTL = timedelta(seconds=60)
#: Сколько последний ответ годен, пока база привязок не отвечает. Дальше —
#: отказ: отключённая за это время учётка не должна работать ботом и дальше.
BINDING_STALE_MAX = timedelta(minutes=10)


def is_allowed(user_id: int | None, allowed_ids: frozenset[int]) -> bool:
    """Разрешён ли этот Telegram ID окружением. Отсутствие ID — нет."""
    return user_id is not None and user_id in allowed_ids


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _standing_from_db(telegram_id: int) -> Standing:
    """Положение из базы. Отдельной функцией модуля — её подменяют тесты бота без базы."""
    return bot_links.standing(telegram_id)


class BindingCache:
    """Опознание по привязке с коротким кэшем и запасным ответом при отказе базы.

    Запасной ответ — затем, чтобы аудитор на точке не остался без бота из-за
    короткого сбоя базы (вопрос 3). Он годен не дольше `BINDING_STALE_MAX` от
    последнего ответа базы: дольше нечем узнать, не отключили ли учётку, и
    тогда — отказ (ревью #340, п.6). Незнакомого при отказе базы не пускаем:
    узнать его нечем.
    """

    def __init__(
        self,
        standing: Callable[[int], Standing] | None = None,
        ttl: timedelta = BINDING_TTL,
        now: Callable[[], datetime] = _utc_now,
        stale_max: timedelta = BINDING_STALE_MAX,
    ) -> None:
        self._standing = standing if standing is not None else _standing_from_db
        self._ttl = ttl
        self._now = now
        self._stale_max = stale_max
        self._known: dict[int, tuple[datetime, Standing]] = {}

    def standing_of(self, telegram_id: int) -> Standing | None:
        """Положение Telegram ID — или `None`: база молчит, а годного ответа нет."""
        сейчас = self._now()
        было = self._known.get(telegram_id)
        if было is not None and сейчас - было[0] < self._ttl:
            return было[1]
        try:
            ответ = self._standing(telegram_id)
        except DbError:
            if было is not None and сейчас - было[0] < self._stale_max:
                logger.warning(
                    "привязки не прочитались, Telegram ID %s — по последнему ответу", telegram_id
                )
                return было[1]
            logger.warning(
                "привязки не прочитались, Telegram ID %s — годного ответа нет, отказ", telegram_id
            )
            return None
        self._known[telegram_id] = (сейчас, ответ)
        return ответ

    def forget(self, telegram_id: int) -> None:
        """Забыть ответ: после погашения ссылки привязка уже другая."""
        self._known.pop(telegram_id, None)


class AccessMiddleware(BaseMiddleware):
    """Внешняя мидлварь: пространство человека в `data[SPACE_KEY]` — или не пускать."""

    def __init__(
        self,
        allowed_ids: frozenset[int],
        bindings: BindingCache | None,
        roster: Roster | None,
        redeem: Callable[..., Binding | None] = bot_links.redeem,
    ) -> None:
        self._allowed_ids = allowed_ids
        self._bindings = bindings
        self._roster = roster
        self._redeem = redeem

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = user.id if user is not None else None
        if user_id is None:
            return None
        метка = _link_token(event)
        if метка is not None:
            await self._link(event, метка, user_id)
            return None
        space = await asyncio.to_thread(self._space_of, user_id)
        if space is None:
            logger.warning("отклонено обновление от постороннего Telegram ID %s", user_id)
            return None
        data[SPACE_KEY] = space
        return await handler(event, data)

    async def _link(self, event: TelegramObject, метка: str, user_id: int) -> None:
        """Погасить ссылку привязки и ответить в тот же чат — и только."""
        привязка = await asyncio.to_thread(self._redeem, метка, telegram_id=user_id)
        if self._bindings is not None:
            self._bindings.forget(user_id)
        if привязка is None:
            logger.warning("негодная ссылка привязки от Telegram ID %s", user_id)
            await _answer(event, "access.link_invalid")
            return
        logger.info("Telegram ID %s привязан к учётке %s", user_id, привязка.login)
        await _answer(event, "access.linked", login=привязка.login)

    def _space_of(self, user_id: int) -> str | None:
        return space_from(
            user_id,
            self._bindings.standing_of(user_id) if self._bindings is not None else NEVER_BOUND,
            allowed_ids=self._allowed_ids,
            roster=self._roster,
        )


def space_from(
    user_id: int,
    положение: Standing | None,
    *,
    allowed_ids: frozenset[int],
    roster: Roster | None,
) -> str | None:
    """Пространство человека — или `None`: бот его не пускает.

    Одно правило на бота и мини-апп (D372): кнопку меню видит каждый, кто
    открыл бота, и мини-апп обязан пускать ровно тех же, кого пускает бот.
    """
    if положение is None:
        # База молчит дольше допустимого: ни привязку, ни её отсутствие
        # сверить нечем — совместимость тоже не применяется (п.6).
        return None
    if положение.binding is not None:
        return canonical_tenant(положение.binding.tenant)
    if положение.ever_bound:
        # Отвязан или учётка отключена: прежний пропуск из окружения не
        # возвращает того, у кого доступ сняли (п.5).
        return None
    # Совместимость (вопрос 2): кто пускался до D286 — сотрудник УК. Только
    # если привязки не было никогда — это проверено выше.
    откуда = _compat_source(user_id, allowed_ids, roster)
    if откуда is None:
        return None
    logger.warning("путь совместимости: Telegram ID %s пущен как УК (%s)", user_id, откуда)
    return HQ_TENANT


def _compat_source(user_id: int, allowed_ids: frozenset[int], roster: Roster | None) -> str | None:
    if is_allowed(user_id, allowed_ids):
        return "ALLOWED_TELEGRAM_IDS"
    if roster is not None and roster.knows(user_id):
        return "roster.json"
    return None


def _link_token(event: TelegramObject) -> str | None:
    """Токен из `/start link-<токен>` — или `None`. Прочие `/start` сюда не относятся."""
    if not isinstance(event, Message):
        return None
    команда, _, метка = (event.text or "").partition(" ")
    if команда.split("@", 1)[0] != "/start" or not метка.startswith(LINK_PREFIX):
        return None
    return метка.removeprefix(LINK_PREFIX).strip() or None


async def _answer(event: TelegramObject, key: str, **params: object) -> None:
    """Ответ в тот же чат, на языке чата."""
    if not isinstance(event, Message):
        return
    await event.answer(t(key, chat_ui_lang(event.chat.id), **params))


def chat_tenant(chat_id: int) -> str | None:
    """Тенант проверки, идущей в чате, — или `None`, если проверки нет или она не читается.

    Нечитаемое состояние — не повод молча отказывать: его разбирает обработчик
    своим отказом (`src/bot/errors.py`), а заслон пропускает апдейт дальше.
    """
    try:
        состояние = read_inspection(chat_id)
    except DomainError:
        # `read_inspection` сводит любой сбой чтения к `DomainError`.
        return None
    return состояние.tenant if состояние is not None else None


class ChatSpaceMiddleware(BaseMiddleware):
    """Проверка в чате принадлежит пространству, а не чату (Review Focus 6).

    Состояние проверки привязано к чату. В общем чате или после переезда
    человека в другое пространство его кнопки и кадры дописывали бы чужую
    проверку. Чат без проверки заслон не касается: новую человек начнёт в своём.
    """

    def __init__(self, read_tenant: Callable[[int], str | None] = chat_tenant) -> None:
        self._read_tenant = read_tenant

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        space = data.get(SPACE_KEY)
        chat = _chat_of(event)
        if space is None or chat is None:
            return await handler(event, data)
        чья = await asyncio.to_thread(self._read_tenant, chat.id)
        if чья is None or canonical_tenant(чья) == space:
            return await handler(event, data)
        logger.warning(
            "апдейт из пространства %s к проверке пространства %s в чате %s", space, чья, chat.id
        )
        текст = t("access.foreign_space", chat_ui_lang(chat.id))
        if isinstance(event, CallbackQuery):
            await event.answer(текст, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(текст)
        return None


def _chat_of(event: TelegramObject) -> Chat | None:
    if isinstance(event, Message):
        return event.chat
    if isinstance(event, CallbackQuery) and isinstance(event.message, Message):
        return event.message.chat
    return None
