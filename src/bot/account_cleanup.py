"""Удаление учёток после 30 дней ожидания. Личные данные стираются, история остаётся."""

import asyncio
import logging

from src.db import user_deletion
from src.db.space import SYSTEM_SPACE, acting_space

logger = logging.getLogger(__name__)
CHECK_EVERY_SEC = 3600


def run_once() -> int:
    """Один ограниченный проход; БД сама блокирует строки и сверяет срок."""
    return user_deletion.purge_due()


async def run_forever() -> None:
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                count = await asyncio.to_thread(run_once)
                if count:
                    logger.info("Удаление учёток: очищено %s", count)
            except Exception:
                logger.exception("Удаление учёток: проход не завершён, повтор через час")
            await asyncio.sleep(CHECK_EVERY_SEC)
