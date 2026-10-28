"""Данные Dodo IS для «Качества» по странам: продажи, агрегаторы, оценки клиентов (D671).

**Почему в боте** — как у входов Dodo IS (`dodois_loader.py`): бот единственный процесс продукта,
который живёт всё время и уже ведёт фоновые задачи; второго расписания не заводим.

**Как.** Раз в `CHECK_EVERY` заход под замком базы (`job_lock`): у каждой страны с действующим
входом собирается то, чья последняя удачная загрузка старше суток (`src/dodois/metrics.py`).
Ключи вход не продлевает — это дело `dodois_loader`. Занят замок — заход пропускается.

**Людям бот не пишет:** итог только в `dodois.metric_loads`, оповещений нет. Служебная работа без
человека: в базу — от имени служебного пространства (F-037).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from src.db.errors import DbError
from src.db.job_lock import DODOIS_METRICS_LOCK_KEY, job_lock
from src.db.space import SYSTEM_SPACE, acting_space
from src.dodois import metrics

logger = logging.getLogger(__name__)

CHECK_EVERY = timedelta(hours=1)


def run_once() -> None:
    """Один заход под замком; занят другим процессом — пропуск, не ошибка."""
    with job_lock(DODOIS_METRICS_LOCK_KEY, what="данные Dodo IS для «Качества»") as got:
        if not got:
            logger.info("Данные Dodo IS: сбор ведёт другой процесс — заход пропущен")
            return
        metrics.run_pass()


async def run_forever() -> None:
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                await asyncio.to_thread(run_once)
            except DbError:
                logger.warning("Данные Dodo IS: база отказала, заход пропущен", exc_info=True)
            except Exception:
                # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
                logger.exception("Данные Dodo IS: непредвиденный сбой захода")
            await asyncio.sleep(CHECK_EVERY.total_seconds())
