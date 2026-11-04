"""Постоянная проверка подключений (D638, #1251): раз в 15 минут — пробы ключей и служб.

**Что.** Ключи OpenAI и iSpring, сам бот (`getMe`) и хранилище кадров — по одной
дешёвой пробе каждое (`src/health/checks.py`); Pointer — только по кнопке (#1256). Исход
ложится в `health.checks`, вкладка «Администрирование → Подключения» выводит из него цвет.
Сборы здесь не пробуются: их цвет — из их же журналов загрузок.

**Оповещения.** После каждого захода `src/health/alerts.py` сверяет цвета с последним
оповещённым состоянием и при смене пишет владельцу в канал FURCA (D641, его «да» на текст и
адресата). Тот же заход зовёт и загрузчик входов Dodo IS (`dodois_loader.py`).

**Покрытие данных рейтингов.** Тем же кругом, раз в сутки после утреннего часа, идёт проверка
«страна × источник» (`src/health/coverage_check.py`, D704, D706): пустые и неполные источники
приходят владельцу в тот же канал.

Упавшая проба не роняет цикл: исход других подключений важнее одного сбоя.
"""

from __future__ import annotations

import asyncio
import logging

from src.db.errors import DbError
from src.db.space import SYSTEM_SPACE, acting_space
from src.health import alerts, coverage_check
from src.health.checks import PROBE_EVERY, SCHEDULED_CODES, probe_and_record

logger = logging.getLogger(__name__)


def probe_all() -> None:
    """Один заход: пробовать всё и записать исходы."""
    for code in SCHEDULED_CODES:
        try:
            probe_and_record(code)
        except DbError:
            logger.warning("Проверка подключений: исход %s не записался", code, exc_info=True)
        except Exception:
            logger.exception("Проверка подключений: проба %s упала", code)


async def check_forever() -> None:
    alerts.log_startup()
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                await asyncio.to_thread(probe_all)
                await asyncio.to_thread(alerts.run_pass_safely)
                await asyncio.to_thread(coverage_check.run_daily_safely)
            except Exception:
                # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
                logger.exception("Проверка подключений: непредвиденный сбой")
            await asyncio.sleep(PROBE_EVERY.total_seconds())
