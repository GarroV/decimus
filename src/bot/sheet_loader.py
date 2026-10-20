"""Раз в несколько часов и по заявке — забор общей таблицы контроля «база рейтингов»
(D464, docs/15-ratings.md).

**Почему в боте** — как у карт и агрегаторов (`maps_loader`, `agg_loader`): бот
единственный живёт всё время и уже ведёт фоновые задачи; второго механизма
расписания не заводим.

**Как.** Раз в минуту смотрит таблицу заявок «Забрать сейчас» (`ratings.sheet_sync_requests`):
заявка есть — забирает сразу и закрывает её исходом. Раз в `SYNC_EVERY_SEC`, если с
последнего захода по таблице прошло столько же, забирает по расписанию. Любой заход,
удачный или нет, считается: сломанная таблица пробуется снова через интервал, а не
каждую минуту. Итог по каждому листу — в `ratings.sheet_sync` и в журнале загрузок, его
видно на «Загрузках». После удачного захода живые точки рейтингов заводятся в
справочник пиццерий (D556, `src/ratings/directory_feed.py`). Адрес таблицы —
`RATINGS_SHEET_ID`; не задан — по расписанию не делает ничего, а заявку закрывает
отказом с причиной. Людям бот о заборе не пишет.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from src.db import ratings_sync as state
from src.db.errors import PushError, RatingsError
from src.db.space import SYSTEM_SPACE, acting_space
from src.ratings import directory_feed, sheet_sync

logger = logging.getLogger(__name__)

POLL_EVERY_SEC = 60
ERROR_LIMIT = 500


def _due() -> bool:
    """Пора ли по расписанию: таблицу ещё не брали или брали давно."""
    if not sheet_sync.configured():
        return False
    seen = state.states()
    if not seen:
        return True
    last = max(s.checked_at for s in seen)
    return (datetime.now(UTC) - last).total_seconds() >= sheet_sync.SYNC_EVERY_SEC


def _failures(results: tuple[sheet_sync.TabResult, ...]) -> str | None:
    failed = [f"{r.tab}: {r.note}" for r in results if r.outcome == sheet_sync.FAILED]
    return "; ".join(failed)[:ERROR_LIMIT] if failed else None


def _tick() -> None:
    """Один заход: заявка — всегда; расписание — когда пора."""
    request = state.open_request()
    if request is None and not _due():
        return
    try:
        results = sheet_sync.run()
    except sheet_sync.SyncError as exc:
        error: str | None = f"{exc.code}: {exc}"
    except Exception as exc:  # заявка не должна висеть из-за непредвиденного сбоя (F-124)
        logger.exception("рейтинги: забор таблицы контроля упал")
        error = type(exc).__name__
    else:
        error = _failures(results)
    if error:
        logger.warning("рейтинги: забор таблицы контроля не удался: %s", error)
    else:
        _feed_directory()
    if request is not None:
        state.finish_request(request.id, ok=error is None, error=error)


def _feed_directory() -> None:
    """Справочник пиццерий — из свежих рейтингов (D556): новая точка появляется на
    «Странах» с первой оценкой, без ручной загрузки. Сбой справочника забор рейтингов
    не отменяет — он уже записан; сбой виден в журнале бота."""
    try:
        report = directory_feed.sync()
    except (PushError, RatingsError):
        logger.warning("рейтинги: справочник пиццерий не обновился", exc_info=True)
        return
    for problem in report.skipped:
        logger.warning("рейтинги: точка не заведена в справочник — %s", problem)


async def load_forever() -> None:
    """Задача бота: забирает таблицу контроля по расписанию и по заявкам.

    Служебная работа без человека: в базу — от имени служебного пространства
    (F-037, `src/db/space.py`).
    """
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                await asyncio.to_thread(_tick)
            except RatingsError:
                logger.warning("рейтинги: забор таблицы контроля — база отказала", exc_info=True)
            except Exception:
                # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
                logger.exception("рейтинги: непредвиденный сбой забора таблицы контроля")
            await asyncio.sleep(POLL_EVERY_SEC)
