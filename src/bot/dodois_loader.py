"""Входы в Dodo IS по странам: ночью продлевает, раз в час проверяет «открыто X из Y» (D640).

**Почему в боте** — как у карт, агрегаторов и обучения: бот единственный процесс продукта,
который живёт всё время и уже ведёт фоновые задачи; второго расписания не заводим.

**Что.** Раз в `CHECK_EVERY` заход: каждый вход, которому пора (ночное окно, раз в сутки; а
истёкший ключ доступа — в любой час), продлевается; затем каждый вход проверяется — список
работающих пиццерий страны и стопы с ключом страны, только чтение. Исход — в `dodois.logins`,
вкладка «Подключения» выводит из него цвет строки страны.

**Один процесс на заход.** Ключ продления одноразовый: заход идёт под замком базы
(`job_lock`), занят — пропускается. Ключей приложения нет — вход помечается «сбой», загрузка
ждёт ключей без перезапуска.

**Тревог наружу нет**: красный виден на экране; сообщение людям — только по «да» владельца.

Служебная работа без человека: в базу — от имени служебного пространства (F-037).
"""

from __future__ import annotations

import asyncio
import logging

from src.db.errors import DbError
from src.db.job_lock import DODOIS_LOADER_LOCK_KEY, job_lock
from src.db.space import SYSTEM_SPACE, acting_space
from src.dodois import service
from src.domain.dodois import CHECK_EVERY

logger = logging.getLogger(__name__)


def run_once() -> None:
    """Один заход под замком; занят другим процессом — пропуск, не ошибка."""
    with job_lock(DODOIS_LOADER_LOCK_KEY, what="входы Dodo IS") as got:
        if not got:
            logger.info("Dodo IS: заход ведёт другой процесс — пропущен")
            return
        service.run_pass()


async def run_forever() -> None:
    with acting_space(SYSTEM_SPACE):
        while True:
            try:
                await asyncio.to_thread(run_once)
            except DbError:
                logger.warning("Dodo IS: база отказала, заход пропущен", exc_info=True)
            except Exception:
                # Упавшая задача asyncio молчит — поэтому ловим всё и живём дальше.
                logger.exception("Dodo IS: непредвиденный сбой захода")
            await asyncio.sleep(CHECK_EVERY.total_seconds())
