"""Дозагрузка кадров, не легших в хранилище на сдаче (#459).

Хранилище кадров прода живёт на MUSPELHEIM, а тот засыпает и сам не
просыпается (D259). Сдача от этого не встаёт: отчёт и письмо собираются из
кадров телеграма, проверка ложится в базу, а кадры остаются в ней строками с
пустым `storage_path` (`db.PhotosDeferredError`). Вернуть их в хранилище потом —
работа этого модуля.

**Почему здесь, а не ночным скриптом площадки.** Байты кадра после сдачи есть
только у телеграма, а токен — только у бота (`src/bot/photos.py`). Скрипт по
расписанию потребовал бы токена вне бота и задачи в cron площадки; проход внутри
бота не требует ни того, ни другого и начинает доливать сам, как только
хранилище проснулось.

**Повторяемо и безопасно.** Берутся только кадры без ссылки; ключ объекта
собран из идентификаторов, так что повторно положенный кадр ляжет на то же
место; ссылку записывает только тот, кто успел первым (`db.upload_photos`).
Сломанный проход ничего не портит — следующий доделает остаток.

**Не молчит.** Кадр, который не вернулся, назван в журнале на каждом проходе:
и когда хранилище лежит, и когда телеграм кадр не отдал. Людям бот отсюда не
пишет ничего — рассылка без владельца не заводится.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram import Bot

from src import db

from .photos import MAX_PARALLEL, fetch_bytes

if TYPE_CHECKING:  # pragma: no cover — только для проверки типов
    from src.db.storage import PhotoStorage

logger = logging.getLogger(__name__)

#: Как часто проверять невыгруженное. Хранилище просыпается, когда разбудили
#: машину, — полчаса между этим и доливкой никому не мешают.
BACKFILL_EVERY_SEC = 30 * 60
#: Кадр моложе этого не трогаем: его, скорее всего, прямо сейчас выгружает сама
#: сдача (`routers.finish.archive`) с байтами на руках.
MIN_AGE_SEC = 10 * 60

FetchAsync = Callable[[str], Awaitable[bytes | None]]


@dataclass(frozen=True)
class BackfillResult:
    """Итог одного прохода — для журнала и проверок."""

    #: Сколько кадров ждало выгрузки в начале прохода.
    pending: int
    #: Сколько легло в хранилище этим проходом.
    uploaded: int
    #: Сколько телеграм не отдал — они остаются ждать следующего прохода.
    missing: int
    #: Хранилище не приняло кадр — проход остановлен до следующего раза.
    storage_down: bool


async def _download(file_ids: tuple[str, ...], fetch: FetchAsync) -> dict[str, bytes]:
    limit = asyncio.Semaphore(MAX_PARALLEL)

    async def one(file_id: str) -> tuple[str, bytes | None]:
        async with limit:
            return file_id, await fetch(file_id)

    pairs = await asyncio.gather(*(one(file_id) for file_id in file_ids))
    return {file_id: raw for file_id, raw in pairs if raw is not None}


async def backfill_once(
    fetch: FetchAsync,
    *,
    min_age_sec: int = MIN_AGE_SEC,
    storage: PhotoStorage | None = None,
) -> BackfillResult:
    """Один проход: всё, что ждёт, — скачать у телеграма и положить в хранилище.

    Отказ хранилища останавливает проход на первой же проверке: остальные
    упрутся в то же, а качать их у телеграма впустую незачем. Отказ базы
    поднимается наружу (`db.DbError`) — его разбирает `backfill_forever`.

    `storage` подменяется только проверками.
    """
    pending = await asyncio.to_thread(db.pending_photo_uploads, min_age_sec=min_age_sec)
    total = sum(len(one.file_ids) for one in pending)
    uploaded = missing = 0
    for one in pending:
        got = await _download(one.file_ids, fetch)
        lost = [file_id for file_id in one.file_ids if file_id not in got]
        if lost:
            missing += len(lost)
            logger.warning(
                "дозагрузка: телеграм не отдал %d кадр(ов) проверки %s — ждут следующего прохода",
                len(lost),
                one.inspection_id,
            )
        try:
            uploaded += await asyncio.to_thread(
                db.upload_photos,
                one.inspection_id,
                fetch=got.get,
                storage=storage,
                # Не отданные телеграмом кадры названы выше и остаются с пустой
                # ссылкой: следующий проход попробует их снова.
                allow_missing=True,
            )
        except db.PhotosDeferredError as exc:
            logger.warning("дозагрузка: хранилище недоступно, кадров ждёт %d: %s", total, exc)
            return BackfillResult(total, uploaded, missing, storage_down=True)
    return BackfillResult(total, uploaded, missing, storage_down=False)


async def backfill_forever(bot: Bot) -> None:
    """Проход по расписанию, пока бот работает. Отказ одного прохода — не конец."""

    async def fetch(file_id: str) -> bytes | None:
        return await fetch_bytes(bot, file_id)

    while True:
        try:
            result = await backfill_once(fetch)
        except db.ConfigError as exc:
            # Базы или хранилища в этой конфигурации нет — доливать некуда.
            logger.info("дозагрузка кадров не ведётся: %s", exc)
            return
        except db.DbError:
            logger.exception("дозагрузка кадров: проход не удался")
        except Exception:
            # Упавшая задача asyncio молчит до отмены: дозагрузка остановилась
            # бы навсегда, и никто бы не узнал. Ошибка в журнал, проход — дальше.
            logger.exception("дозагрузка кадров: проход упал")
        else:
            if result.pending:
                logger.info(
                    "дозагрузка: легло кадров %d из %d, телеграм не отдал %d%s",
                    result.uploaded,
                    result.pending,
                    result.missing,
                    ", хранилище недоступно" if result.storage_down else "",
                )
        await asyncio.sleep(BACKFILL_EVERY_SEC)
