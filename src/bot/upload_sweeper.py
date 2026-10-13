"""Уборка брошенных кадров мини-аппа по расписанию (F-033, #531) и старых записей журналов.

Что убирается и что никогда — `src/domain/upload_sweep.py`. Здесь — когда:
задача живёт в боте рядом с уборкой копий кадров (`frame_copies`) и дозагрузкой
(`photo_backfill`), потому что у бота есть и папка состояния, и база.

**Без базы не убирает.** Ссылки сданных проверок знает только база; не
прочиталась она — проход пропускается целиком и повторяется в следующий раз.
Удалить кадр сданной проверки, не легший в хранилище, — потерять
доказательство; подержать брошенный кадр ещё несколько часов — ничего.
"""

from __future__ import annotations

import asyncio
import logging

from src import db
from src.db import journals
from src.db.photos import walk_photo_refs
from src.domain import check_environment
from src.domain.upload_sweep import SweepResult, sweep_uploads

logger = logging.getLogger(__name__)

#: Как часто проходить. Срок кадра — неделя, точность до часов не нужна.
SWEEP_EVERY_SEC = 6 * 60 * 60


def sweep_once() -> SweepResult | None:
    """Один проход. `None` — пропущен: база не ответила или не настроена."""
    try:
        keep = walk_photo_refs()
    except db.DbError as exc:
        logger.warning("уборка кадров мини-аппа пропущена: база не ответила (%s)", exc)
        return None
    return sweep_uploads(check_environment(), keep=keep)


async def sweep_forever() -> None:
    """Уборка, пока бот работает. Отказ одного прохода — не конец уборки."""
    while True:
        try:
            result = await asyncio.to_thread(sweep_once)
            if result is not None and (result.frames or result.marks or result.parts):
                logger.info(
                    "убраны брошенные кадры мини-аппа: кадров %s, меток %s, обрывков %s",
                    result.frames,
                    result.marks,
                    result.parts,
                )
        except Exception:
            logger.exception("уборка кадров мини-аппа не прошла")
        await _purge_journals()
        await asyncio.sleep(SWEEP_EVERY_SEC)


async def _purge_journals() -> None:
    """Срок хранения журналов входов (180 дней) и действий (365), D462. Сбой — в журнал процесса."""
    try:
        убрано = await asyncio.to_thread(journals.purge)
        if убрано:
            logger.info("убрано старых записей журналов входов и действий: %s", убрано)
    except Exception:
        logger.exception("уборка журналов входов и действий не прошла")
