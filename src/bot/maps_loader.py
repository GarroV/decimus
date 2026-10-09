"""Раз в сутки — оценки пиццерий на картах из Pointer (docs/09-pointer-api.md).

**Почему в боте.** Бот — единственный процесс продукта, который живёт всё
время и уже ведёт фоновые задачи (`photo_backfill`, `frame_copies`); cron на
площадке был бы вторым механизмом расписания, которого никто не найдёт.

**Как.** Раз в час: если удачной загрузки не было `FRESH_FOR_SEC`, загрузить.
Неудача пишется в журнал `maps.loads` и в лог; следующая попытка — через час.
Ключа нет — задача молча не работает и говорит об этом один раз при старте.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime

from src.db import maps_store
from src.db.errors import RatingsError
from src.ratings import maps
from src.ratings.pointer import PointerError

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60


def _due() -> bool:
    last = maps_store.last_ok_load()
    return last is None or (datetime.now(UTC) - last).total_seconds() >= FRESH_FOR_SEC


async def load_forever() -> None:
    """Задача бота: держит снимок оценок карт не старше суток."""
    if not os.environ.get(maps.KEY_ENV, "").strip():
        logger.info("Оценки карт: %s не задан — загрузка выключена", maps.KEY_ENV)
        return
    while True:
        try:
            if await asyncio.to_thread(_due):
                await asyncio.to_thread(maps.load_once)
        except (PointerError, RatingsError) as exc:
            logger.warning("Оценки карт не загрузились: %s", exc)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки карт: непредвиденный сбой загрузки")
        await asyncio.sleep(CHECK_EVERY_SEC)
