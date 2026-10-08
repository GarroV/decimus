"""Сдана ли проверка: признак, который ставит бот, а читают и бот, и мини-апп (D080, D312).

Сданная проверка запечатана: отчёт отдан, история точки узнаёт его по слепку
содержимого, и дописанная после сдачи запись легла бы в историю второй строкой
(`src/bot/sealed.py`). Ставит признак бот — он собирает и отдаёт отчёт, — и
лежит признак в его заметках рядом с состоянием (`bot.json`). Мини-апп обхода
пишет в ту же проверку и обязан упираться в тот же запрет, а слой бота ему
недоступен (`lint-imports`). Поэтому имя файла, ключ и значение «не сдавалась»
живут здесь, а бот берёт их отсюда же.

Проверка «не сдана» перед записью делается под замком заметок
(`while_open`): бот ставит признак тем же замком (`sidecar._lock`), поэтому
сдача не может проскочить между проверкой и записью — запись либо целиком
ложится до сдачи, либо получает отказ.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import check_environment
from .engine import chat_dir
from .errors import DomainError
from .state import state_lock

NOTES_FILE_NAME = "bot.json"
HANDED_OVER_KEY = "handed_over_findings"

#: «Отчёт по этой проверке не отдавался». Не `0`: ноль записей — законная
#: сданная проверка (чистая точка).
NEVER_HANDED_OVER = -1


class HandedOverError(DomainError):
    """Проверка сдана: запись в неё не принимается (D080)."""


def _notes_path(chat_id: int) -> Path:
    return chat_dir(chat_id, check_environment()) / NOTES_FILE_NAME


def handed_over(chat_id: int) -> bool:
    """Отдан ли отчёт по проверке чата. Испорченные заметки — отказ, а не «не сдана».

    Молчаливое «не сдана» на непонятном файле открыло бы правку запечатанной
    проверки ровно тогда, когда что-то уже пошло не так.
    """
    path = _notes_path(chat_id)
    if not path.is_file():
        return False
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DomainError(f"Заметки бота не читаются: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise DomainError(f"Заметки бота не похожи на заметки — не объект: {path}")
    raw = data.get(HANDED_OVER_KEY)
    if raw is None:
        return False
    try:
        return int(raw) != NEVER_HANDED_OVER
    except (TypeError, ValueError) as exc:
        raise DomainError(f"Признак сдачи в заметках {path} не число: {raw!r}") from exc


@contextmanager
def while_open(chat_id: int) -> Iterator[None]:
    """Держать проверку несданной на время записи: проверка и запись — под одним замком.

    Замок — заметки бота (`bot.json.lock`), тот же, под которым бот ставит
    признак сдачи. Пока блок внутри идёт, сдача ждёт; сданная к началу блока
    проверка — `HandedOverError` до записи. Замок проверки (`inspection.json.lock`)
    — другой файл, и движок внутри блока берёт его как обычно.
    """
    with state_lock(_notes_path(chat_id)):
        if handed_over(chat_id):
            raise HandedOverError(f"Проверка чата {chat_id} сдана — запись не принимается")
        yield
