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

**Оценки поштучно (#1562, D732).** Тем же кругом, в том же замке — шаг загрузки отзывов
`maps_reviews.reviews_step`: история за год, потом раз в сутки два последних месяца. После
того как все пары на сегодня закрыты, раз в сутки — сверка со счётчиком карточки: расхождение
пишется в лог, людям ничего не уходит.

**Один процесс на заход (F-125).** «Пора» решается по отметке в базе, и два процесса
(перекрывшийся контейнер при выкатке, второй экземпляр) видят одну и ту же отметку и
оба тянут из Pointer и пишут: двойная квота и задвоенные строки. Загрузка и шаг истории
идут под замком базы (`src/db/job_lock.py`, как у сборщика агрегаторов); замок занят —
этот процесс заход молча пропускает, работу уже делает другой.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from src.db import maps_store, service_keys
from src.db.errors import DbError, RatingsError
from src.db.job_lock import MAPS_LOADER_LOCK_KEY, job_lock
from src.db.space import SYSTEM_SPACE, acting_space
from src.health import checks
from src.ratings import maps, maps_reviews, pointer
from src.ratings.pointer import PointerError

logger = logging.getLogger(__name__)

CHECK_EVERY_SEC = 60 * 60
FRESH_FOR_SEC = 20 * 60 * 60
#: Глубина истории — год: столько отдаёт Pointer (docs/09-pointer-api.md).
HISTORY_MONTHS = 12
#: Запросов истории за час: ~1 с на запрос, то есть не больше пяти минут работы за круг.
HISTORY_REQUESTS_PER_CYCLE = 300
#: Запросов отзывов за круг: столько же, сколько у истории оценок филиалов.
REVIEWS_REQUESTS_PER_CYCLE = 300


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


@dataclass
class ReviewsState:
    """Память цикла об оценках поштучно: за какой день сверка уже сделана."""

    reconciled_on: date | None = None


def reviews_cycle(state: ReviewsState, fetch: pointer.Fetch | None = None) -> bool:
    """Один шаг загрузки оценок; `True` — на сегодня всё загружено и сверено."""
    today = _today()
    step = maps_reviews.reviews_step(
        today=today,
        fetch=fetch or maps._key_fetch(),
        max_requests=REVIEWS_REQUESTS_PER_CYCLE,
    )
    if step.requests:
        logger.info(
            "Оценки карт поштучно: за круг запросов %d, оценок легло %d, закрыто: %s",
            step.requests,
            step.saved,
            step.done,
        )
    if step.done and state.reconciled_on != today:
        mismatches, unchecked, total = maps_reviews.reconcile()
        text = maps_reviews.report(mismatches, unchecked, total)
        (logger.warning if mismatches else logger.info)("%s", text)
        state.reconciled_on = today
    return step.done


def _load_if_due(history: HistoryState) -> None:
    """Суточная загрузка, когда пора; под замком — «пора» и загрузка не разрываются."""
    with job_lock(MAPS_LOADER_LOCK_KEY, what="оценки карт") as got:
        if not got:
            logger.info("Оценки карт: загрузку ведёт другой процесс — заход пропущен")
            return
        if _due():
            # Отпечаток ключа снимается ДО загрузки: см. `checks.record_key_in_use`.
            fingerprint = _key_fingerprint()
            maps.load_once()
            history.done = False  # в загрузке могли прийти новые филиалы
            if fingerprint is not None:
                _confirm_key(fingerprint)


def _key_fingerprint() -> bytes | None:
    """Отпечаток ключа Pointer; не прочитался — загрузка идёт, проверка ключа не засчитывается."""
    try:
        return service_keys.probe_snapshot("pointer").fingerprint
    except DbError:
        logger.warning("Ключ Pointer: отпечаток не снялся", exc_info=True)
        return None


def _confirm_key(fingerprint: bytes) -> None:
    """Удачная суточная загрузка — это и проверка ключа Pointer (#1425)."""
    try:
        checks.record_key_in_use("pointer", fingerprint)
    except DbError:
        logger.warning("Ключ Pointer: удачная загрузка не записалась как проверка", exc_info=True)


def _history_step(history: HistoryState) -> None:
    """Шаг дозагрузки истории под тем же замком, что и суточная загрузка."""
    with job_lock(MAPS_LOADER_LOCK_KEY, what="оценки карт") as got:
        if not got:
            logger.info("История карт: загрузку ведёт другой процесс — заход пропущен")
            return
        history_cycle(history)


def _reviews_step(state: ReviewsState) -> None:
    """Шаг загрузки оценок под тем же замком, что и суточная загрузка."""
    with job_lock(MAPS_LOADER_LOCK_KEY, what="оценки карт") as got:
        if not got:
            logger.info("Оценки карт поштучно: загрузку ведёт другой процесс — заход пропущен")
            return
        reviews_cycle(state)


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
    reviews = ReviewsState()
    while True:
        try:
            await asyncio.to_thread(_load_if_due, history)
        except (PointerError, RatingsError) as exc:
            logger.warning("Оценки карт не загрузились: %s", exc)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки карт: непредвиденный сбой загрузки")
        try:
            await asyncio.to_thread(_history_step, history)
        except (PointerError, RatingsError) as exc:
            logger.warning("История карт не догрузилась, продолжим в следующий круг: %s", exc)
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("История карт: непредвиденный сбой дозагрузки")
        try:
            await asyncio.to_thread(_reviews_step, reviews)
        except (PointerError, RatingsError) as exc:
            logger.warning(
                "Оценки карт поштучно не догрузились, продолжим в следующий круг: %s", exc
            )
        except Exception:
            # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
            logger.exception("Оценки карт поштучно: непредвиденный сбой загрузки")
        await asyncio.sleep(CHECK_EVERY_SEC)
