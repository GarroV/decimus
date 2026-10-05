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

**Не молчит, но и не шумит вечно.** Кадр, который не вернулся, назван в
журнале: и когда хранилище лежит, и когда телеграм кадр не отдал. Кадр старше
`STALE_AFTER_SEC` уходит из частого прохода в редкий — раз в сутки, со сводкой
«ждёт N суток» без стека: иначе кадр, которого телеграм не отдаст никогда, вечно
занимал бы выборку и журнал. Людям бот отсюда не пишет ничего — рассылка без
владельца не заводится.

**Живучесть.** Отказ одной проверки не обрывает проход, отказ прохода не
обрывает задачу, а незаданная конфигурация перепроверяется на следующем
проходе: упавшая задача asyncio молчит, и дозагрузка встала бы незаметно.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from aiogram import Bot

from src import db
from src.db.config import load_storage_settings
from src.db.photos import PENDING_BATCH
from src.db.storage import S3PhotoStorage

from .photos import MAX_PARALLEL, fetch_bytes

logger = logging.getLogger(__name__)

#: Как часто проверять невыгруженное. Хранилище просыпается, когда разбудили
#: машину, — полчаса между этим и доливкой никому не мешают.
BACKFILL_EVERY_SEC = 30 * 60
#: Кадр моложе этого не трогаем: его, скорее всего, прямо сейчас выгружает сама
#: сдача (`routers.finish.archive`) с байтами на руках.
MIN_AGE_SEC = 10 * 60
#: Кадр старше этого уходит в редкий проход. Двое суток — с запасом на выходные
#: спящего MUSPELHEIM в пределах частого прохода и не больше.
STALE_AFTER_SEC = 2 * 24 * 60 * 60
#: Редкий проход и сводка по застарелым — раз в сутки.
STALE_EVERY_SEC = 24 * 60 * 60
#: Сколько застарелых кадров брать за редкий проход.
STALE_BATCH = 200

_SEC_PER_DAY = 24 * 60 * 60

FetchAsync = Callable[[str], Awaitable[bytes | None]]


class BackfillStorage(Protocol):
    """Хранилище, которое умеет и принять кадр, и дёшево сказать, живо ли оно."""

    def put(self, key: str, data: bytes, *, content_type: str) -> str: ...

    def delete(self, key: str) -> None: ...

    def ping(self) -> None: ...


@dataclass(frozen=True)
class BackfillResult:
    """Итог одного прохода — для журнала и проверок."""

    #: Сколько кадров ждало выгрузки в начале прохода.
    pending: int
    #: Сколько легло в хранилище этим проходом.
    uploaded: int
    #: Сколько телеграм не отдал — они остаются ждать.
    missing: int
    #: Хранилище не ответило — проход остановлен до следующего раза.
    storage_down: bool
    #: Сколько проверок не выгрузилось по другой причине (названы в журнале).
    failed: int = 0
    #: С какого момента ждёт самый старый кадр прохода; `None` — ждать нечему.
    oldest: datetime | None = None


async def _download(file_ids: tuple[str, ...], fetch: FetchAsync) -> dict[str, bytes]:
    limit = asyncio.Semaphore(MAX_PARALLEL)

    async def one(file_id: str) -> tuple[str, bytes | None]:
        async with limit:
            return file_id, await fetch(file_id)

    pairs = await asyncio.gather(*(one(file_id) for file_id in file_ids))
    return {file_id: raw for file_id, raw in pairs if raw is not None}


def _storage(total: int) -> BackfillStorage:
    """Быстрый клиент из окружения. `S3_*` нет при непустой очереди — это ошибка вслух."""
    try:
        return S3PhotoStorage(load_storage_settings(), fail_fast=True)
    except db.ConfigError as exc:
        logger.error("дозагрузка: хранилище не настроено, кадров ждёт %d: %s", total, exc)
        raise


async def backfill_once(
    fetch: FetchAsync,
    *,
    min_age_sec: int = MIN_AGE_SEC,
    max_age_sec: int | None = STALE_AFTER_SEC,
    limit: int = PENDING_BATCH,
    storage: BackfillStorage | None = None,
) -> BackfillResult:
    """Один проход: всё, что ждёт, — скачать у телеграма и положить в хранилище.

    Хранилище спрашивается до телеграма (`ping`): лежит — качать незачем.
    Отказ хранилища посреди прохода останавливает проход — остальные упрутся в
    то же. Прочий отказ одной проверки (`db.PushError`) назван в журнале с её
    идентификатором, и проход идёт дальше. Нет базы или `S3_*` —
    `db.ConfigError` наружу, его разбирает `backfill_forever`.

    `storage` подменяется только проверками.
    """
    pending = await asyncio.to_thread(
        db.pending_photo_uploads, min_age_sec=min_age_sec, max_age_sec=max_age_sec, limit=limit
    )
    total = sum(len(one.file_ids) for one in pending)
    oldest = min((one.waiting_since for one in pending), default=None)
    if not pending:
        return BackfillResult(0, 0, 0, storage_down=False)
    store = storage if storage is not None else _storage(total)
    try:
        await asyncio.to_thread(store.ping)
    except db.StorageError as exc:
        logger.warning("дозагрузка: хранилище недоступно, кадров ждёт %d: %s", total, exc)
        return BackfillResult(total, 0, 0, storage_down=True, oldest=oldest)

    uploaded = missing = failed = 0
    for one in pending:
        got = await _download(one.file_ids, fetch)
        lost = [file_id for file_id in one.file_ids if file_id not in got]
        if lost:
            missing += len(lost)
            logger.warning(
                "дозагрузка: телеграм не отдал %d кадр(ов) проверки %s — ждут дальше",
                len(lost),
                one.inspection_id,
            )
        try:
            uploaded += await asyncio.to_thread(
                db.upload_photos,
                one.inspection_id,
                fetch=got.get,
                storage=store,
                # Не отданные телеграмом кадры названы выше и остаются с пустой
                # ссылкой: следующий проход попробует их снова.
                allow_missing=True,
            )
        except db.PhotosDeferredError as exc:
            logger.warning("дозагрузка: хранилище недоступно, кадров ждёт %d: %s", total, exc)
            return BackfillResult(
                total, uploaded, missing, storage_down=True, failed=failed, oldest=oldest
            )
        except db.PushError as exc:
            failed += 1
            logger.warning("дозагрузка: проверка %s не выгружена: %s", one.inspection_id, exc)
    return BackfillResult(
        total, uploaded, missing, storage_down=False, failed=failed, oldest=oldest
    )


def _log_pass(result: BackfillResult, *, stale: bool) -> None:
    if not result.pending:
        return
    if stale:
        дней = 0.0
        if result.oldest is not None:
            дней = (datetime.now(UTC) - result.oldest).total_seconds() / _SEC_PER_DAY
        logger.warning(
            "дозагрузка: кадров ждёт дольше %d суток: %d, дольше всех — %.0f суток; "
            "легло %d, телеграм не отдал %d, хранилище %s",
            STALE_AFTER_SEC // _SEC_PER_DAY,
            result.pending,
            дней,
            result.uploaded,
            result.missing,
            "недоступно" if result.storage_down else "на связи",
        )
        return
    logger.info(
        "дозагрузка: легло кадров %d из %d, телеграм не отдал %d, отказов %d%s",
        result.uploaded,
        result.pending,
        result.missing,
        result.failed,
        ", хранилище недоступно" if result.storage_down else "",
    )


async def _pass(fetch: FetchAsync, *, stale: bool) -> None:
    """Один проход с разбором отказов: ни один из них не роняет задачу."""
    try:
        if stale:
            result = await backfill_once(
                fetch, min_age_sec=STALE_AFTER_SEC, max_age_sec=None, limit=STALE_BATCH
            )
        else:
            result = await backfill_once(fetch)
    except db.ConfigError as exc:
        # Базы или хранилища в конфигурации нет. Не конец задачи: окружение
        # перепроверяется на следующем проходе. Непустая очередь при
        # ненастроенном хранилище уже названа ошибкой в `_storage`.
        logger.info("дозагрузка кадров в этот проход не ведётся: %s", exc)
    except db.DbError:
        logger.exception("дозагрузка кадров: проход не удался")
    except Exception:
        # Упавшая задача asyncio молчит до отмены: дозагрузка остановилась
        # бы навсегда, и никто бы не узнал. Ошибка в журнал, задача — дальше.
        logger.exception("дозагрузка кадров: проход упал")
    else:
        _log_pass(result, stale=stale)


async def backfill_forever(bot: Bot) -> None:
    """Проход по расписанию, пока бот работает; раз в сутки — по застарелым."""

    async def fetch(file_id: str) -> bytes | None:
        return await fetch_bytes(bot, file_id)

    last_stale = float("-inf")
    while True:
        await _pass(fetch, stale=False)
        if time.monotonic() - last_stale >= STALE_EVERY_SEC:
            last_stale = time.monotonic()
            await _pass(fetch, stale=True)
        await asyncio.sleep(BACKFILL_EVERY_SEC)
