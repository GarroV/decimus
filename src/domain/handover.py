"""Сдана ли проверка: признак, который ставит бот, а читают и бот, и мини-апп (D080, D312).

Сданная проверка запечатана: отчёт отдан, история точки узнаёт его по слепку
содержимого, и дописанная после сдачи запись легла бы в историю второй строкой
(`src/bot/sealed.py`). Ставит признак бот — он собирает и отдаёт отчёт, — и
лежит признак в его заметках рядом с состоянием (`bot.json`). Мини-апп обхода
пишет в ту же проверку и обязан упираться в тот же запрет, а слой бота ему
недоступен (`lint-imports`). Поэтому имя файла, ключ и значение «не сдавалась»
живут здесь, а бот берёт их отсюда же.
"""

from __future__ import annotations

import json
from typing import Any

from .config import check_environment
from .engine import chat_dir
from .errors import DomainError

NOTES_FILE_NAME = "bot.json"
HANDED_OVER_KEY = "handed_over_findings"

#: «Отчёт по этой проверке не отдавался». Не `0`: ноль записей — законная
#: сданная проверка (чистая точка).
NEVER_HANDED_OVER = -1


def handed_over(chat_id: int) -> bool:
    """Отдан ли отчёт по проверке чата. Испорченные заметки — отказ, а не «не сдана».

    Молчаливое «не сдана» на непонятном файле открыло бы правку запечатанной
    проверки ровно тогда, когда что-то уже пошло не так.
    """
    path = chat_dir(chat_id, check_environment()) / NOTES_FILE_NAME
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
