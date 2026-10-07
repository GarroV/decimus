"""Отказ базы словами для вошедшего — без устройства стенда (#515).

Слой `db` пишет отказ так, чтобы его понял оператор: расхождение подключений
(`DatabaseTargetError`) называет каждую базу, хост, порт и роль — без пароля,
но всё равно это карта стенда. Командам в терминале она нужна; вошедшему в
админку, в том числе партнёру, — нет. Поэтому экран показывает общий текст и
отсылает к администратору, а подробности уходят в журнал сервера на уровне
ERROR, где их найдёт тот, кто чинит.

Узнать расхождение и записать его в журнал — общее правило веба и MCP, оно
живёт в `src/db/target_refusal.py`; здесь только текст экрана.
"""

from __future__ import annotations

from src.db.target_refusal import note_target_mismatch

from .texts import t

#: Ключ общего текста в каталоге (`texts_refusals.py`). Тот же ключ — код отказа
#: MCP `db_target` (`src/mcp/db_target.py`): текст один на обе поверхности.
DB_TARGET_KEY = "refusal.db_target"

__all__ = ["DB_TARGET_KEY", "note_target_mismatch", "public_reason"]


def public_reason(exc: BaseException, lang: str) -> str:
    """Текст отказа для экрана: расхождение баз — общими словами, прочее — как есть."""
    if note_target_mismatch(exc):
        return t(DB_TARGET_KEY, lang)
    return str(exc)
