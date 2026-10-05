"""Отказы, которые останавливают мастер проверки: журнал и счётчик (#436).

С 24.09 (D196) до 29.09 бот отказывал аудитору, если пиццерии не было в
справочнике, и об этом узнали только по скриншоту: отказ не попадал никуда, и
посчитать, сколько людей упёрлось так же, было нечем. Поэтому каждый отказ,
после которого мастер дальше не идёт, проходит здесь — одной дверью, а не
россыпью вызовов журнала по обработчикам, где следующий отказ его бы забыл.

Что пишется: код шага (`start.unit`, `finish.archive`), причина — ключ текста,
который увидел человек (`start.unit_need_number`), и Telegram ID. Имени нет
нигде: ID достаточно, чтобы посчитать людей, и он ничего не говорит постороннему,
читающему журнал. Бот работает в личной переписке, где ID чата и есть ID человека.

Куда пишется — в двух местах, и у каждого своя работа:

* журнал контейнера (`logger.warning`) — чтобы отказ был виден рядом с
  остальным, что делал бот в ту минуту;
* `STOPS_FILE_NAME` в каталоге состояния, строка JSON на отказ, — чтобы
  админ мог посчитать отказы за период командой `/stops`, не разбирая журнал
  контейнера, который живёт до перезапуска.

**Отказ записи не роняет ответ человеку.** Не записалась строка — это потеря
сведений для подсчёта, а не повод оставить аудитора без сообщения.

**Счётчик хранит `STOPS_RETENTION_DAYS` дней, не больше** (#501). Строки
старше обрезаются при записи, как только самая старая строка файла вышла за
срок: файл перестаёт расти по строке на отказ навсегда, а `/stops` спрашивает
период не длиннее того же срока — иначе он молча считал бы меньше, чем
спросили. Обрезка переписывает файл целиком во временный рядом и подменяет его
атомарно (`os.replace`), а запись и обрезка идут под одной блокировкой файла
(`flock` на `<файл>.lock`): иначе строка, дописанная между чтением и подменой,
ушла бы в старый файл и пропала вместе с ним.

Сообщений никому, кроме самого аудитора, отсюда не уходит: «повторяющийся отказ
доходит до владельца» — это сообщение человеку, а такие отправки — только по
явному «да» владельца на текст и адресатов. Пока его нет, владелец сам
открывает счётчик (`/stops`).
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aiogram.types import InlineKeyboardMarkup, Message

from src.domain import check_environment
from src.domain.errors import DomainError

from .texts import t

logger = logging.getLogger(__name__)

#: Файл счётчика в каталоге состояния: строка JSON на отказ.
STOPS_FILE_NAME = "bot-stops.jsonl"

#: Сколько дней счётчик помнит отказ (#501). Он же — предел периода `/stops`.
STOPS_RETENTION_DAYS = 90
STOPS_RETENTION = timedelta(days=STOPS_RETENTION_DAYS)

#: Суффикс файла блокировки. Отдельный файл, а не сам счётчик: счётчик при
#: обрезке подменяется другим, и блокировка на нём осталась бы на старом.
LOCK_SUFFIX = ".lock"


@dataclass(frozen=True)
class StopCount:
    """Сколько раз за период отказал шаг по этой причине и скольким людям."""

    step: str
    reason: str
    times: int
    people: int


def stops_path() -> Path:
    """Файл счётчика. Отказ окружения — `DomainError`, как у всего блока."""
    return check_environment().state_dir / STOPS_FILE_NAME


def _now() -> datetime:
    return datetime.now(UTC)


def note_stop(telegram_id: int, *, step: str, reason: str) -> None:
    """Записать отказ: строка в журнал контейнера и строка в счётчик."""
    logger.warning("отказ мастера: шаг=%s причина=%s telegram_id=%s", step, reason, telegram_id)
    line = {
        "at": _now().isoformat(),
        "step": step,
        "reason": reason,
        "telegram_id": telegram_id,
    }
    try:
        path = stops_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(path):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            if _prune_due(path, _now()):
                _prune_locked(path, _now())
    except (OSError, DomainError):
        logger.exception("отказ мастера (шаг %s) не записался в счётчик", step)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Исключительная блокировка счётчика на время записи или обрезки."""
    lock = path.with_name(path.name + LOCK_SUFFIX)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _first_line(path: Path) -> str:
    with path.open(encoding="utf-8") as f:
        return f.readline()


def _prune_due(path: Path, now: datetime) -> bool:
    """Пора ли обрезать: самая старая (первая) строка вышла за срок или не читается.

    Строки дописываются по времени, поэтому смотреть дальше первой не нужно, и
    обычная запись не перечитывает файл целиком.
    """
    parsed = _parse(_first_line(path))
    return parsed is None or parsed[0] < now - STOPS_RETENTION


def prune_stops(*, path: Path | None = None, now: datetime | None = None) -> int:
    """Обрезать счётчик до срока хранения. Возвращает, сколько строк убрано."""
    source = path or stops_path()
    if not source.exists():
        return 0
    with _locked(source):
        return _prune_locked(source, now or _now())


def _prune_locked(path: Path, now: datetime) -> int:
    """Оставить строки не старше срока и подменить файл атомарно. Блокировка — на вызывающем.

    Испорченные строки уходят вместе со старыми: посчитать их нельзя, а
    оставленные, они делали бы обрезку «пора» на каждой записи.
    """
    cutoff = now - STOPS_RETENTION
    kept: list[str] = []
    dropped = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse(raw)
        if parsed is not None and parsed[0] >= cutoff:
            kept.append(raw)
        elif raw.strip():
            dropped += 1
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(row + "\n" for row in kept))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    if dropped:
        logger.info(
            "счётчик отказов обрезан до %d дней: убрано строк %d", STOPS_RETENTION_DAYS, dropped
        )
    return dropped


async def refuse(
    message: Message,
    lang: str,
    *,
    step: str,
    key: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **fmt: Any,
) -> None:
    """Сказать человеку об отказе текстом `key` и записать отказ шага `step`.

    Причина в счётчике — тот же ключ, что у текста: так по счётчику видно, что
    именно человек прочитал, а ключи, в отличие от формулировок, не правятся.
    """
    note_stop(message.chat.id, step=step, reason=key)
    await message.answer(t(key, lang, **fmt), reply_markup=reply_markup)


def _parse(raw: str) -> tuple[datetime, str, str, int] | None:
    try:
        row = json.loads(raw)
        return (
            datetime.fromisoformat(row["at"]),
            str(row["step"]),
            str(row["reason"]),
            int(row["telegram_id"]),
        )
    except (ValueError, KeyError, TypeError):
        return None


def count_stops(since: datetime, *, path: Path | None = None) -> list[StopCount]:
    """Отказы с момента `since`: по шагу и причине, сколько раз и скольким людям.

    Порядок — от самого частого. Испорченная строка пропускается и называется в
    журнале: одна битая строка не должна прятать весь счётчик.
    """
    source = path or stops_path()
    if not source.exists():
        return []
    times: Counter[tuple[str, str]] = Counter()
    people: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    broken = 0
    for raw in source.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        parsed = _parse(raw)
        if parsed is None:
            broken += 1
            continue
        at, step, reason, who = parsed
        if at < since:
            continue
        times[(step, reason)] += 1
        people[(step, reason)].add(who)
    if broken:
        logger.warning("в счётчике отказов %d испорченных строк — пропущены", broken)
    return [
        StopCount(step=step, reason=reason, times=n, people=len(people[(step, reason)]))
        for (step, reason), n in sorted(times.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
