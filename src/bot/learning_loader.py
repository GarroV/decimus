"""Раз в сутки — обучение пиццерий из iSpring в нашу базу (D574, D575, #906; docs/20-training.md).

**Почему в боте** — как у карт и агрегаторов (`maps_loader`, `agg_loader`): бот единственный
процесс продукта, который живёт всё время и уже ведёт фоновые задачи; второго механизма
расписания не заводим.

**Как.** Раз в час: если удачной загрузки не было `FRESH_FOR_SEC`, загрузить. Исход — в
журнал `learning.loads`. Ключей iSpring нет (ни в базе, ни в окружении) — заход молча
пропускается, а при старте и при первом пропуске об этом говорит лог (один раз): ключи
ставят на экране «Ключи сервисов», и загрузка начнётся без перезапуска.

**Один процесс на заход.** «Пора» решается по отметке в базе; загрузка идёт под замком
базы (`job_lock`), занят — заход пропускается: работу ведёт другой процесс.

**Тревога.** Первый сбой после удачной загрузки — одна тревога в канал FURCA владельцу
(`aggregators/alert.channel/send`, D438); повторные часовые попытки молчат до успеха.
Текст — без ключей и без данных: в него идёт только тип сбоя и путь запроса.

Служебная работа без человека: в базу — от имени служебного пространства (F-037).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime

from src.db import learning_store
from src.db.errors import DbError
from src.db.job_lock import LEARNING_LOADER_LOCK_KEY, job_lock
from src.db.space import SYSTEM_SPACE, acting_space
from src.learning import keys
from src.learning.ispring import IspringError
from src.learning.sync import run
from src.ratings.aggregators import alert

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60


@dataclass
class State:
    """Память цикла: говорили ли про отсутствие ключей и слали ли тревогу о текущем сбое."""

    no_keys_told: bool = False
    alerted: bool = False


def _due() -> bool:
    last = learning_store.last_ok_load()
    return last is None or (datetime.now(UTC) - last).total_seconds() >= FRESH_FOR_SEC


def load_if_due(state: State) -> str | None:
    """Заход под замком. Возвращает текст сбоя (для тревоги) или `None`."""
    with job_lock(LEARNING_LOADER_LOCK_KEY, what="обучение") as got:
        if not got:
            logger.info("Обучение: загрузку ведёт другой процесс — заход пропущен")
            return None
        if not _due():
            return None
        client = keys.client()
        if client is None:
            if not state.no_keys_told:
                logger.info("Обучение: ключи iSpring не заданы — загрузка ждёт ключей")
                state.no_keys_told = True
            return None
        state.no_keys_told = False
        try:
            summary = run(client)
        except (IspringError, DbError) as exc:
            logger.warning("Обучение не загрузилось: %s", exc)
            learning_store.log_load(ok=False, error=str(exc))
            return str(exc)
        learning_store.log_load(ok=True, departments=summary.departments, results=summary.results)
        logger.info(
            "Обучение загружено: пиццерий %d (сопоставлено %d), назначений %d",
            summary.pizzerias,
            summary.matched,
            summary.results,
        )
        return None


async def _notify(reason: str) -> None:
    target = alert.channel(os.environ)
    if target is None:
        return
    try:
        await asyncio.to_thread(
            alert.send, target, f"Децимус: загрузка обучения из iSpring не прошла. {reason}"[:400]
        )
    except Exception:
        logger.exception("Обучение: тревога о сбое не ушла")


async def load_forever() -> None:
    with acting_space(SYSTEM_SPACE):
        await _load_forever()


async def _load_forever() -> None:
    state = State()
    while True:
        try:
            failure = await asyncio.to_thread(load_if_due, state)
            if failure is None:
                state.alerted = False
            elif not state.alerted:
                state.alerted = True
                await _notify(failure)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Обучение: непредвиденный сбой загрузки")
        await asyncio.sleep(CHECK_EVERY_SEC)
