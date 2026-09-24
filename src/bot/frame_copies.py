"""Копии присланных кадров на диске площадки, на 7 дней (#367, решение владельца D179).

Кадр в проверке хранится идентификатором телеграма (`bot.json`, `frames`), а
файл лежит у телеграма. Для отчёта этого хватает, для разбора — нет: хранить
файлы вечно телеграм не обещает, а разбирать боевой случай приходится и через
несколько дней. Поэтому кадр копируется при получении и лежит неделю.

**Срок — решение владельца, а не удобство.** На кадрах бывают лица сотрудников,
поэтому копии живут 7 дней и убираются сами. По той же причине каталог копий —
отдельный том, а не папка состояния: состояние уходит в ночной бэкап с хранением
14 дней (`docs/08-deploy.md`, §4.7), и копии прожили бы там вдвое дольше
названного срока.

Каталог не задан (`FRAMES_DIR`) — копии не делаются, о чём бот говорит один раз
при подъёме. Не задан он законно там, где разбирать нечего: тесты, замеры.

Имя копии — отпечаток идентификатора кадра (`copy_name`): тем же именем кадр
назван в журнале разбора (`bot.journal`), и найти файл по строке журнала можно
без таблицы соответствий.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path

from aiogram import Bot

from . import journal
from .photos import fetch_bytes

logger = logging.getLogger(__name__)

FRAMES_DIR_VAR = "FRAMES_DIR"
#: Срок хранения копии — решение владельца D179.
KEEP_DAYS = 7
KEEP_SEC = KEEP_DAYS * 24 * 60 * 60
#: Как часто убирать просроченное. Час — копия переживает срок не больше чем на час.
SWEEP_EVERY_SEC = 60 * 60
COPY_SUFFIX = ".jpg"

#: Фоновые скачивания держатся ссылкой, иначе сборщик мусора снимает задачу на
#: середине (так устроен `asyncio.create_task`).
_running: set[asyncio.Task[None]] = set()


def frames_dir() -> Path | None:
    """Каталог копий — или ничего, если копии на этом стенде не ведутся."""
    raw = (os.environ.get(FRAMES_DIR_VAR) or "").strip()
    return Path(raw) if raw else None


def copy_name(file_id: str) -> str:
    """Имя копии по идентификатору кадра. Тем же именем кадр назван в журнале."""
    return hashlib.sha256(file_id.encode()).hexdigest()[:24] + COPY_SUFFIX


def copy_path(root: Path, chat_id: int, file_id: str) -> Path:
    return root / f"chat_{chat_id}" / copy_name(file_id)


def _write(target: Path, raw: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


async def _copy(bot: Bot, target: Path, file_id: str) -> None:
    if await asyncio.to_thread(target.exists):
        return
    raw = await fetch_bytes(bot, file_id)
    if raw is None:
        # Причина уже в журнале контейнера (`fetch_bytes`); проверка идёт
        # дальше — кадр у телеграма остался, пропала только копия для разбора.
        return
    try:
        await asyncio.to_thread(_write, target, raw)
    except OSError:
        logger.exception("копия кадра %s не записалась в %s", file_id, target)


def keep(bot: Bot | None, chat_id: int, file_ids: Iterable[str]) -> None:
    """Скопировать кадры в фоне. Аудитор ответа не ждёт: скачивание — не его забота."""
    root = frames_dir()
    if root is None or bot is None:
        return
    for file_id in file_ids:
        task = asyncio.create_task(_copy(bot, copy_path(root, chat_id, file_id), file_id))
        _running.add(task)
        task.add_done_callback(_running.discard)


def received(bot: Bot | None, chat_id: int, frames: Iterable[tuple[int, str]]) -> None:
    """Кадры пришли: строка в журнал разбора и копии в фоне.

    Зовётся рядом с `sidecar.remember_frames` на каждом входе кадра — это одно
    и то же событие, увиденное с трёх сторон: список присланного, журнал и копия.
    """
    pairs = list(frames)
    journal.note(
        chat_id,
        "frames",
        frames=[
            {"message_id": message_id, "file_id": file_id, "copy": copy_name(file_id)}
            for message_id, file_id in pairs
        ],
    )
    keep(bot, chat_id, [file_id for _, file_id in pairs])


def sweep(root: Path, *, now: float | None = None) -> int:
    """Удалить копии старше срока. Вернуть, сколько удалено.

    Возраст — по времени записи файла, то есть по времени получения кадра:
    копия делается в момент, когда кадр пришёл.
    """
    moment = time.time() if now is None else now
    removed = 0
    if not root.is_dir():
        return 0
    for path in root.glob(f"chat_*/*{COPY_SUFFIX}"):
        try:
            if moment - path.stat().st_mtime > KEEP_SEC:
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed


async def sweep_forever() -> None:
    """Уборка по расписанию, пока бот работает. Отказ одного прохода — не конец уборки."""
    root = frames_dir()
    if root is None:
        logger.warning(
            "копии кадров для разбора не ведутся: %s не задан (#367, D179)", FRAMES_DIR_VAR
        )
        return
    while True:
        try:
            removed = await asyncio.to_thread(sweep, root)
            if removed:
                logger.info("убрано просроченных копий кадров: %s", removed)
        except OSError:
            logger.exception("уборка копий кадров в %s не прошла", root)
        await asyncio.sleep(SWEEP_EVERY_SEC)
