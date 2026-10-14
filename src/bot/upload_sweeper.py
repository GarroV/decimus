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
from src.db import journals, second_factor
from src.db.photos import walk_photo_refs
from src.domain import check_environment
from src.domain.second_factor import PASSKEY_IDLE_LIMIT
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
        await _purge_idle_passkeys()
        await asyncio.sleep(SWEEP_EVERY_SEC)


async def _purge_journals() -> None:
    """Срок хранения журналов входов (180 дней) и действий (365), D462. Сбой — в журнал процесса."""
    try:
        убрано = await asyncio.to_thread(journals.purge)
        if убрано:
            logger.info("убрано старых записей журналов входов и действий: %s", убрано)
    except Exception:
        logger.exception("уборка журналов входов и действий не прошла")


#: Запись в журнал действий (`action_journal.action`) о снятых за простой ключах (D485).
PASSKEY_EXPIRED_ACTION = "passkey_expired"


def purge_idle_passkeys_once() -> int:
    """Снять ключи доступа, которыми не входили `PASSKEY_IDLE_LIMIT`; каждому человеку — запись.

    Возвращает, сколько ключей снято. Потерянное устройство уходит само; человек при
    следующем входе получит новое сохранение Touch ID.
    """
    снято = second_factor.purge_idle_passkeys(PASSKEY_IDLE_LIMIT)
    for user_id, role, tenant, count in снято:
        journals.record_action(
            user_id=user_id,
            role=role,
            tenant=tenant,
            action=PASSKEY_EXPIRED_ACTION,
            target=f"keys={count}",
            outcome="ok",
            ip=None,
            credential=None,
        )
    return sum(строка[3] for строка in снято)


async def _purge_idle_passkeys() -> None:
    """В каждом проходе (раз в 6 часов; лишний раз снимать безвредно). Сбой — в журнал процесса."""
    try:
        снято = await asyncio.to_thread(purge_idle_passkeys_once)
        if снято:
            logger.info("сняты ключи доступа, которыми не входили 30 дней: %s", снято)
    except Exception:
        logger.exception("снятие простаивающих ключей доступа не прошло")
