"""Расхождение баз в цепочке отказа — узнать и записать в журнал (#515, #521).

Слой `db` пишет расхождение подключений (`DatabaseTargetError`) так, чтобы его
понял оператор: каждая база, хост, порт и роль — без пароля, но это всё равно
карта стенда. Наружу — вошедшему в веб-админку (`src/web/db_refusal.py`) и
агенту за MCP (`src/mcp/db_target.py`) — она не уходит: обе поверхности
отвечают общими словами, а подробности ложатся сюда, в журнал сервера на
уровне ERROR, где их найдёт тот, кто чинит.

Узнаётся расхождение по цепочке причин, а не по типу самого отказа: дверь
учёток (`database_target.same_database_or_deny`) оборачивает его в
`AccessError`, и текст обёртки несёт те же подробности.

Модуль в `db`, а не в одной из поверхностей: веб и MCP — пиры и импортировать
друг друга не могут (`lint-imports`), а правило «узнать и записать» у них одно.
Драйвера базы здесь нет, поэтому модуль импортируется и там, где `psycopg`
не поставлен.
"""

from __future__ import annotations

import logging

from .errors import DatabaseTargetError

logger = logging.getLogger(__name__)


def target_mismatch_in(exc: BaseException) -> DatabaseTargetError | None:
    """Расхождение баз в цепочке причин отказа, если оно там есть."""
    причина: BaseException | None = exc
    while причина is not None:
        if isinstance(причина, DatabaseTargetError):
            return причина
        причина = причина.__cause__
    return None


def note_target_mismatch(exc: BaseException) -> bool:
    """Расхождение баз в цепочке отказа — в журнал на уровне ERROR. Было ли оно."""
    расхождение = target_mismatch_in(exc)
    if расхождение is None:
        return False
    logger.error("подключения стенда ведут в разные базы: %s", расхождение)
    return True
