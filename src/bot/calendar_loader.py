"""Событие срока отчёта в календаре проверяющего — фоновая сводка (D740, D741, #1590).

**Почему в боте** — как у остальных фоновых задач: бот единственный процесс продукта, который
живёт всё время и уже ведёт повторяемую работу; завершение проверки (`finish.py`) при этом
к Google не обращается вовсе, поэтому ни сеть, ни отказ календаря его не задерживают и не ломают.

Что и как сводится — `src/gcal/sync.py`. Здесь только расписание, замок и ссылка на карточку.
Один процесс на проход: замок базы (`job_lock`), занят — пропуск. Служебная работа без человека:
в базу — от имени служебного пространства (F-037). Людям ничего не отправляется.
"""

from __future__ import annotations

import asyncio
import logging

from src.bot.preliminary import card_url
from src.db.errors import DbError
from src.db.job_lock import CALENDAR_LOADER_LOCK_KEY, job_lock
from src.db.space import SYSTEM_SPACE, acting_space
from src.domain.timing import utc_now
from src.gcal import sync

logger = logging.getLogger(__name__)

#: Как часто сводить. Событие появляется через пару минут после завершения проверки.
CHECK_EVERY_SEC = 300


def run_once() -> None:
    """Один проход под замком; занят другим процессом — пропуск, не ошибка."""
    with job_lock(CALENDAR_LOADER_LOCK_KEY, what="календарь срока отчёта") as got:
        if not got:
            logger.info("календарь: проход ведёт другой процесс — пропущен")
            return
        итог = sync.run_pass(today=utc_now().date(), link_for=card_url)
        if итог.created or итог.updated or итог.deleted or итог.failed:
            logger.info(
                "календарь: создано %s, сдвинуто %s, удалено %s, сбоев %s",
                итог.created,
                итог.updated,
                итог.deleted,
                итог.failed,
            )


async def run_forever() -> None:
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                await asyncio.to_thread(run_once)
            except DbError:
                logger.warning("календарь: база отказала, проход пропущен", exc_info=True)
            except Exception:
                # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
                logger.exception("календарь: непредвиденный сбой прохода")
            await asyncio.sleep(CHECK_EVERY_SEC)
