"""Раз в сутки (D389) — оценки пиццерий в агрегаторах доставки (docs/17-aggregators.md).

**Почему в боте** — как у карт (`maps_loader`): бот единственный живёт всё время
и уже ведёт фоновые задачи; второго механизма расписания не заводим.

**Как.** Раз в час: если сбора не было `FRESH_FOR_SEC`, собрать все агрегаторы.
Считается любой сбор, удачный или нет: сломанный агрегатор пробуется снова на
следующие сутки, а не гоняет весь сбор каждый час. Итог по каждому агрегатору —
в журнале `agg.loads`, его видно на странице рейтингов. Ключей не нужно.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from src.db import agg_store
from src.ratings.aggregators import collect

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60


def _due() -> bool:
    last = agg_store.last_run()
    return last is None or (datetime.now(UTC) - last).total_seconds() >= FRESH_FOR_SEC


async def load_forever() -> None:
    """Задача бота: держит снимок оценок агрегаторов не старше суток."""
    while True:
        try:
            if await asyncio.to_thread(_due):
                await asyncio.to_thread(collect.run_all, date.today())
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки агрегаторов: непредвиденный сбой сбора")
        await asyncio.sleep(CHECK_EVERY_SEC)
