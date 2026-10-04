"""Кто говорит с ботом прямо сейчас и какой язык он выбрал (D303, #411).

Язык бота — свойство человека, а не чата и не проверки: в одном чате могут
быть двое, а один человек ведёт много проверок подряд. Поэтому выбор хранится
за Telegram ID (`src/db/bot_langs.py`), а то, ЧЕЙ это апдейт, кладёт мидлварь
в переменную контекста. Так `lang.chat_ui_lang(chat_id)` узнаёт человека, не
меняя подписи ни у одного из десятков своих вызовов.

Выбор читается из базы мидлварью в потоке и дальше живёт в памяти процесса
`CACHE_TTL`; после записи память обновляется тем же ходом.
Отказ базы при чтении не роняет ничего — выбора как будто нет, язык берётся
дальше по цепочке (`lang.py` намеренно не падает на выборе языка). Повторный
поход в базу после отказа — не раньше `RETRY_AFTER`, чтобы молчащая база не
тормозила каждое сообщение.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from src.db import bot_langs

logger = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]

#: Через сколько снова спросить базу о выборе, если она отказала.
RETRY_AFTER = timedelta(seconds=60)
#: Сколько живёт запомненное — и выбор, и «не выбирал» (ревью #492, п.2).
CACHE_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class Person:
    """Человек этого апдейта — его Telegram ID."""

    telegram_id: int


_current: ContextVar[Person | None] = ContextVar("bot_person", default=None)


def current_person() -> Person | None:
    """Человек апдейта, который сейчас обрабатывается; `None` — вне апдейта."""
    return _current.get()


def _load_from_db(telegram_id: int) -> str | None:
    """Чтение из базы. Отдельной функцией модуля — её подменяют тесты бота без базы."""
    return bot_langs.chosen_lang(telegram_id)


def _save_to_db(telegram_id: int, lang: str) -> None:
    """Запись в базу. Отдельной функцией модуля — по той же причине."""
    bot_langs.choose_lang(telegram_id, lang)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LangChoices:
    """Выборы людей: база как источник, память процесса как кэш.

    Чтение разделено надвое (ревью #492, п.1): `load` ходит в базу и зовётся
    мидлварью В ПОТОКЕ (`asyncio.to_thread`), а `cached` только смотрит в
    память — его и зовут обработчики через `lang.chat_ui_lang`. Иначе база,
    теряющая пакеты, замораживала бы цикл событий, то есть все чаты разом.

    Запомненное — и выбор, и «не выбирал» — живёт `CACHE_TTL` (п.2): выбор,
    сделанный мимо этого процесса (второй бот, правка в базе), доезжает сам.
    """

    def __init__(self, now: Callable[[], datetime] = _utc_now) -> None:
        self._now = now
        self._known: dict[int, tuple[datetime, str | None]] = {}
        self._failed: dict[int, datetime] = {}

    def cached(self, telegram_id: int) -> str | None:
        """Выбор из памяти — без похода в базу, даже устаревший: лучше прежний, чем никакого."""
        запись = self._known.get(telegram_id)
        return None if запись is None else запись[1]

    def needs_load(self, telegram_id: int) -> bool:
        """Пора ли спросить базу: нет в памяти или устарело, и база не отказывала только что."""
        сейчас = self._now()
        отказ = self._failed.get(telegram_id)
        if отказ is not None and сейчас - отказ < RETRY_AFTER:
            return False
        запись = self._known.get(telegram_id)
        return запись is None or сейчас - запись[0] >= CACHE_TTL

    def load(self, telegram_id: int) -> None:
        """Прочитать выбор из базы в память. Блокирует — звать в потоке. Наружу не бросает."""
        try:
            выбор = _load_from_db(telegram_id)
        except Exception:
            # Широко намеренно, как в `lang.py`: у выбора языка есть честное
            # умолчание, а немота бота из-за него — та самая поломка T126.
            logger.exception("выбор языка человека %s не прочитался — как без выбора", telegram_id)
            self._failed[telegram_id] = self._now()
            return
        self._failed.pop(telegram_id, None)
        self._known[telegram_id] = (self._now(), выбор)

    def chosen(self, telegram_id: int) -> str | None:
        """Подгрузить при необходимости и вернуть. Блокирует — не для цикла событий."""
        if self.needs_load(telegram_id):
            self.load(telegram_id)
        return self.cached(telegram_id)

    def choose(self, telegram_id: int, lang: str) -> None:
        """Записать выбор. Блокирует — звать в потоке. Отказ базы уходит наружу.

        Память обновляется только после записи: выбор, который не пережил бы
        перезапуск, — не тот, о котором человеку сказали «запомнил».
        """
        _save_to_db(telegram_id, lang)
        self._known[telegram_id] = (self._now(), lang)
        self._failed.pop(telegram_id, None)


#: Выборы этого процесса. Один на бота: `lang.chat_ui_lang` зовётся из модулей,
#: которым диспетчер не передаёт ничего, кроме номера чата.
CHOICES = LangChoices()


class PersonMiddleware(BaseMiddleware):
    """Кладёт человека апдейта в контекст на время его обработки.

    Регистрируется ПЕРВОЙ из внешних мидлварей: отказ по ссылке привязки
    (`access.py`) тоже говорит с человеком и тоже должен знать его язык.
    Сама ничего не отвечает и никого не останавливает.
    """

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = event.from_user if isinstance(event, (Message, CallbackQuery)) else None
        if user is None:
            return await handler(event, data)
        # Прогрев кэша — в потоке: обработчики дальше читают только память
        # (`LangChoices.cached`), и зависшая база держит этот апдейт, а не все.
        if CHOICES.needs_load(user.id):
            await asyncio.to_thread(CHOICES.load, user.id)
        метка = _current.set(Person(telegram_id=user.id))
        try:
            return await handler(event, data)
        finally:
            _current.reset(метка)
