"""Постоянная проверка подключений (D638, #1251): раз в 15 минут — пробы ключей и служб.

**Что.** Ключи OpenAI и iSpring, сам бот (`getMe`) и хранилище кадров — по одной
дешёвой пробе каждое (`src/health/checks.py`); Pointer — только по кнопке (#1256). Исход
ложится в `health.checks`, вкладка «Администрирование → Подключения» выводит из него цвет.
Сборы здесь не пробуются: их цвет — из их же журналов загрузок.

**Тревог наружу нет.** Красный виден на экране; сообщение в Telegram или почту — только
по «да» владельца на текст и адресата (#1251, правило о коммуникации).

Упавшая проба не роняет цикл: исход других подключений важнее одного сбоя.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from src.db import health_store
from src.db.errors import DbError
from src.db.space import SYSTEM_SPACE, acting_space
from src.health.checks import PROBE_EVERY, SCHEDULED_CODES, run_probe

logger = logging.getLogger(__name__)


def probe_all() -> None:
    """Один заход: пробовать всё и записать исходы."""
    for code in SCHEDULED_CODES:
        try:
            outcome = run_probe(code)
        except Exception:
            logger.exception("Проверка подключений: проба %s упала", code)
            continue
        if outcome is None:
            continue
        light, reason = outcome
        try:
            health_store.record(code, light, reason, datetime.now(UTC))
        except DbError:
            logger.warning("Проверка подключений: исход %s не записался", code, exc_info=True)


async def check_forever() -> None:
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                await asyncio.to_thread(probe_all)
            except Exception:
                # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
                logger.exception("Проверка подключений: непредвиденный сбой")
            await asyncio.sleep(PROBE_EVERY.total_seconds())
