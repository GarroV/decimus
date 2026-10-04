"""Кто говорит с ботом прямо сейчас и какой язык он выбрал (D303, #411).

Язык бота — свойство человека, а не чата и не проверки: в одном чате могут
быть двое, а один человек ведёт много проверок подряд. Поэтому выбор хранится
за Telegram ID (`src/db/bot_langs.py`), а то, ЧЕЙ это апдейт, кладёт мидлварь
в переменную контекста. Так `lang.chat_ui_lang(chat_id)` узнаёт человека, не
меняя подписи ни у одного из десятков своих вызовов.

Выбор читается из базы один раз на человека и дальше живёт в памяти процесса:
пишет его только этот бот, и после записи память обновляется тем же ходом.
Отказ базы при чтении не роняет ничего — выбора как будто нет, язык берётся
дальше по цепочке (`lang.py` намеренно не падает на выборе языка). Повторный
поход в базу после отказа — не раньше `RETRY_AFTER`, чтобы молчащая база не
тормозила каждое сообщение.
"""

from __future__ import annotations

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
    """Выборы людей: база как источник, память процесса как кэш."""

    def __init__(self, now: Callable[[], datetime] = _utc_now) -> None:
        self._now = now
        self._known: dict[int, str | None] = {}
        self._failed: dict[int, datetime] = {}

    def chosen(self, telegram_id: int) -> str | None:
        """Выбор человека или `None`: не выбирал — или база сейчас не ответила."""
        if telegram_id in self._known:
            return self._known[telegram_id]
        отказ = self._failed.get(telegram_id)
        if отказ is not None and self._now() - отказ < RETRY_AFTER:
            return None
        try:
            выбор = _load_from_db(telegram_id)
        except Exception:
            # Широко намеренно, как в `lang.py`: у выбора языка есть честное
            # умолчание, а немота бота из-за него — та самая поломка T126.
            logger.exception("выбор языка человека %s не прочитался — как без выбора", telegram_id)
            self._failed[telegram_id] = self._now()
            return None
        self._failed.pop(telegram_id, None)
        self._known[telegram_id] = выбор
        return выбор

    def choose(self, telegram_id: int, lang: str) -> None:
        """Записать выбор. Отказ базы уходит наружу: зовущий говорит человеку, что не вышло.

        Память обновляется только после записи: выбор, который не пережил бы
        перезапуск, — не тот, о котором человеку сказали «запомнил».
        """
        _save_to_db(telegram_id, lang)
        self._known[telegram_id] = lang
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
        метка = _current.set(Person(telegram_id=user.id))
        try:
            return await handler(event, data)
        finally:
            _current.reset(метка)
