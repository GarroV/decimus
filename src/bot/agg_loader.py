"""Раз в сутки (D389) и по заявке (D420) — оценки пиццерий в агрегаторах доставки
(docs/17-aggregators.md).

**Почему в боте** — как у карт (`maps_loader`): бот единственный живёт всё время
и уже ведёт фоновые задачи; второго механизма расписания не заводим.

**Как.** Раз в час: если сбора не было `FRESH_FOR_SEC`, собрать все агрегаторы.
Раз в минуту — только таблица заявок (`queue.POLL_EVERY_SEC`): контроль попросил
обновить кнопкой или через Claude — бот собирает названных сразу, не дожидаясь
суток, и закрывает заявку исходом. Людям бот о сборе не пишет, кроме одного
случая: суточный сбор с ошибками и задан `AGG_ALERT_CHAT_ID` — одно сообщение
этому человеку (`aggregators/alert.py`, D434). Переменная пуста — молчит.
Считается любой сбор, удачный или нет: сломанный агрегатор пробуется снова на
следующие сутки, а не гоняет весь сбор каждый час. Итог по каждому агрегатору —
в журнале `agg.loads`, его видно на странице рейтингов. Ключей не нужно.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Sequence
from datetime import UTC, date, datetime

from aiogram import Bot

from src.db import agg_store
from src.ratings.aggregators import alert, collect, queue

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60


def _due() -> bool:
    last = agg_store.last_run()
    return last is None or (datetime.now(UTC) - last).total_seconds() >= FRESH_FOR_SEC


def _tick(*, scheduled: bool) -> Sequence[collect.Outcome]:
    """Один заход: заявка — всегда; суточный сбор — только на часовом заходе.
    Итоги — только суточного сбора: по ним решается уведомление."""
    if queue.fulfil(today=date.today()):
        return ()  # заявка только что собрала всё, что просили, — расписание подождёт час
    if scheduled and _due():
        return collect.run_all(date.today())
    return ()


async def notify(bot: Bot | None, outcomes: Sequence[collect.Outcome]) -> bool:
    """Сообщить о сбое суточного сбора, если задан адресат. Сбой отправки — в
    журнал: сбор уже записан, а уведомление — не повод ронять задачу."""
    target = alert.chat_id(os.environ.get(alert.CHAT_VAR))
    text = alert.message(outcomes)
    if bot is None or target is None or text is None:
        return False
    try:
        await bot.send_message(target, text)
    except Exception:
        logger.exception("Оценки агрегаторов: уведомление о сбое не ушло")
        return False
    return True


async def load_forever(bot: Bot | None = None) -> None:
    """Задача бота: держит снимок оценок агрегаторов не старше суток и
    выполняет заявки на обновление."""
    since_check = CHECK_EVERY_SEC  # первый заход — сразу и с проверкой расписания
    while True:
        scheduled = since_check >= CHECK_EVERY_SEC
        try:
            outcomes = await asyncio.to_thread(_tick, scheduled=scheduled)
            await notify(bot, outcomes)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки агрегаторов: непредвиденный сбой сбора")
        since_check = 0 if scheduled else since_check + queue.POLL_EVERY_SEC
        await asyncio.sleep(queue.POLL_EVERY_SEC)
