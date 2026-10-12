"""Раз в сутки (D389) и по заявке (D420) — оценки пиццерий в агрегаторах доставки
(docs/17-aggregators.md).

**Почему в боте** — как у карт (`maps_loader`): бот единственный живёт всё время
и уже ведёт фоновые задачи; второго механизма расписания не заводим.

**Как.** Раз в час: если сбора не было `FRESH_FOR_SEC`, собрать все агрегаторы.
Раз в минуту — только таблица заявок (`queue.POLL_EVERY_SEC`): контроль попросил
обновить кнопкой или через Claude — бот собирает названных сразу, не дожидаясь
суток, и закрывает заявку исходом. Людям бот о сборе не пишет.
Считается любой сбор, удачный или нет: сломанный агрегатор пробуется снова на
следующие сутки, а не гоняет весь сбор каждый час. Итог по каждому агрегатору —
в журнале `agg.loads`, его видно на странице рейтингов. Ключей не нужно.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from src.db import agg_store
from src.ratings.aggregators import collect, queue

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60


def _due() -> bool:
    last = agg_store.last_run()
    return last is None or (datetime.now(UTC) - last).total_seconds() >= FRESH_FOR_SEC


def _tick(*, scheduled: bool) -> None:
    """Один заход: заявка — всегда; суточный сбор — только на часовом заходе."""
    if queue.fulfil(today=date.today()):
        return  # заявка только что собрала всё, что просили, — расписание подождёт час
    if scheduled and _due():
        collect.run_all(date.today())


async def load_forever() -> None:
    """Задача бота: держит снимок оценок агрегаторов не старше суток и
    выполняет заявки на обновление."""
    since_check = CHECK_EVERY_SEC  # первый заход — сразу и с проверкой расписания
    while True:
        scheduled = since_check >= CHECK_EVERY_SEC
        try:
            await asyncio.to_thread(_tick, scheduled=scheduled)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки агрегаторов: непредвиденный сбой сбора")
        since_check = 0 if scheduled else since_check + queue.POLL_EVERY_SEC
        await asyncio.sleep(queue.POLL_EVERY_SEC)
