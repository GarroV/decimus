"""Раз в сутки — оценки пиццерий на картах из Pointer (docs/09-pointer-api.md).

**Почему в боте.** Бот — единственный процесс продукта, который живёт всё
время и уже ведёт фоновые задачи (`photo_backfill`, `frame_copies`); cron на
площадке был бы вторым механизмом расписания, которого никто не найдёт.

**Как.** Раз в час: если удачной загрузки не было `FRESH_FOR_SEC`, загрузить.
Неудача пишется в журнал `maps.loads` и в лог; следующая попытка — через час.
Ключа нет — задача молча не работает и говорит об этом один раз при старте.

**История (#616).** Тем же циклом каждый час доливается история оценок филиалов на
`HISTORY_MONTHS` месяцев — порциями до `HISTORY_REQUESTS_PER_CYCLE` запросов. Что
уже легло, определяет база, а не память процесса: выкатка, пересоздавшая контейнер,
ничего не теряет, первый же час после старта продолжает с места. Закрытая история
больше часа не тратит; новый день и новая суточная загрузка (новые филиалы) открывают
проверку заново.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from src.db import maps_store
from src.db.errors import RatingsError
from src.db.space import SYSTEM_SPACE, acting_space
from src.ratings import maps, pointer
from src.ratings.pointer import PointerError

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60
#: Глубина истории — год: столько отдаёт Pointer (docs/09-pointer-api.md).
HISTORY_MONTHS = 12
#: Запросов истории за час: ~1 с на запрос, то есть не больше пяти минут работы за круг.
HISTORY_REQUESTS_PER_CYCLE = 300


def _due() -> bool:
    last = maps_store.last_ok_load()
    return last is None or (datetime.now(UTC) - last).total_seconds() >= FRESH_FOR_SEC


@dataclass
class HistoryState:
    """Память цикла о дозагрузке истории: закрыта ли и что уже пробовалось сегодня."""

    done: bool = False
    day: date | None = None
    attempted: set[tuple[str, date]] = field(default_factory=set)

    def roll(self, today: date) -> None:
        """Новый день — пробуем заново и окна без данных тоже."""
        if self.day != today:
            self.day, self.done = today, False
            self.attempted.clear()


def _today() -> date:
    return datetime.now(UTC).date()


def history_cycle(state: HistoryState, fetch: pointer.Fetch | None = None) -> bool:
    """Один шаг дозагрузки истории; `True` — закрыта, до завтра тратить нечего."""
    state.roll(_today())
    if state.done:
        return True
    step = maps.backfill_step(
        HISTORY_MONTHS,
        today=_today(),
        max_requests=HISTORY_REQUESTS_PER_CYCLE,
        fetch=fetch,
        attempted=state.attempted,
    )
    if step.requests:
        logger.info(
            "История карт: за круг запросов %d, оценок легло %d, закрыта: %s",
            step.requests,
            step.saved,
            step.done,
        )
    state.done = step.done
    return step.done


async def load_forever() -> None:
    """Задача бота: держит снимок оценок карт не старше суток.

    Служебная работа без человека: в базу — от имени служебного пространства
    (F-037, `src/db/space.py`).
    """
    with acting_space(SYSTEM_SPACE):
        await _load_forever()


async def _load_forever() -> None:
    """Задача бота: держит снимок оценок карт не старше суток."""
    if not os.environ.get(maps.KEY_ENV, "").strip():
        logger.info("Оценки карт: %s не задан — загрузка выключена", maps.KEY_ENV)
        return
    history = HistoryState()
    while True:
        try:
            if await asyncio.to_thread(_due):
                await asyncio.to_thread(maps.load_once)
                history.done = False  # в загрузке могли прийти новые филиалы
        except (PointerError, RatingsError) as exc:
            logger.warning("Оценки карт не загрузились: %s", exc)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки карт: непредвиденный сбой загрузки")
        try:
            await asyncio.to_thread(history_cycle, history)
        except (PointerError, RatingsError) as exc:
            logger.warning("История карт не догрузилась, продолжим в следующий круг: %s", exc)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("История карт: непредвиденный сбой дозагрузки")
        await asyncio.sleep(CHECK_EVERY_SEC)
