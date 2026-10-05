"""Отказ базы словами для вошедшего — без устройства стенда (#515).

Слой `db` пишет отказ так, чтобы его понял оператор: расхождение подключений
(`DatabaseTargetError`) называет каждую базу, хост, порт и роль — без пароля,
но всё равно это карта стенда. Командам в терминале она нужна; вошедшему в
админку, в том числе партнёру, — нет. Поэтому экран показывает общий текст и
отсылает к администратору, а подробности уходят в журнал сервера на уровне
ERROR, где их найдёт тот, кто чинит.

Расхождение узнаётся по цепочке причин, а не по типу самого отказа: дверь
учёток (`database_target.same_database_or_deny`) оборачивает его в
`AccessError`, и текст обёртки несёт те же подробности.
"""

from __future__ import annotations

import logging

from src.db.errors import DatabaseTargetError

from .texts import t

logger = logging.getLogger(__name__)

#: Ключ общего текста в каталоге (`texts_refusals.py`).
DB_TARGET_KEY = "refusal.web.db_target"


def _target_error(exc: BaseException) -> DatabaseTargetError | None:
    причина: BaseException | None = exc
    while причина is not None:
        if isinstance(причина, DatabaseTargetError):
            return причина
        причина = причина.__cause__
    return None


def note_target_mismatch(exc: BaseException) -> bool:
    """Расхождение баз в цепочке отказа — в журнал на уровне ERROR. Было ли оно.

    Для экранов, которые и так говорят общими словами («перечень сейчас
    неизвестен»): им текст не нужен, но расхождение не должно пропасть молча.
    """
    расхождение = _target_error(exc)
    if расхождение is None:
        return False
    logger.error("подключения стенда ведут в разные базы: %s", расхождение)
    return True


def public_reason(exc: BaseException, lang: str) -> str:
    """Текст отказа для экрана: расхождение баз — общими словами, прочее — как есть."""
    if note_target_mismatch(exc):
        return t(DB_TARGET_KEY, lang)
    return str(exc)
