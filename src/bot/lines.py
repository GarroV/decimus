"""Строки материала: несколько нарушений из одного комментария или кадра (D718, D713).

Мини-апп обхода делит комментарий с несколькими разными дефектами на отдельные
нарушения (`recognize.split`), и у каждого свой пункт и своя запись. Бот ведёт
себя так же: каждое нарушение — отдельное сообщение со своими кандидатами и
своим слотом в `pending`, запись одного не гасит кнопки другого.

Здесь только то, что не зависит от Telegram: деление слов, группировка увиденного
на кадре по пунктам и сборка «на кадрах видно ещё» по всем строкам. Показ и
запись — в `routers/record.py`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from src.recognize.errors import RecognizeError
from src.recognize.models import Candidate
from src.recognize.split import MAX_PARTS, split_violations

from . import journal
from .usage import chat_usage

logger = logging.getLogger(__name__)

#: Нарушений из одного материала — не больше, как в мини-аппе: платный путь на каждое.
MAX_LINES = MAX_PARTS


async def split_note(chat_id: int, note: str) -> tuple[str, ...]:
    """Отдельные нарушения комментария — слова аудитора, разрезанные по дефектам.

    Один кусок — комментарий как есть. Сбой модели деления не останавливает
    разбор: комментарий уходит одной строкой, как в мини-аппе, а причина — в
    журнал и лог (только тип: слова аудитора в лог не идут).
    """
    said = note.strip()
    if not said:
        return ()
    try:
        with chat_usage(chat_id):
            parts = await asyncio.to_thread(split_violations, said, max_parts=MAX_LINES)
    except (RecognizeError, OSError) as exc:
        logger.warning("комментарий не поделен на нарушения: %s", type(exc).__name__)
        journal.note(chat_id, "split_failed", error=type(exc).__name__)
        return (said,)
    journal.note(chat_id, "split", parts=len(parts))
    return parts or (said,)


def group_by_item(candidates: Sequence[Candidate]) -> list[tuple[Candidate, ...]]:
    """Кандидаты по кадру без слов — по группе на пункт.

    Один пункт — одно нарушение: повторы модели строк не множат, а варианты
    класса и зоны одного пункта остаются в группе вариантами для выбора
    (мини-апп делит ещё и по зоне — `walk_batch._distinct`; в боте один пункт в
    двух зонах — это сомнение модели о месте, а не два нарушения). Порядок — как
    ответила модель.
    """
    groups: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.code, []).append(candidate)
    return [tuple(group) for group in groups.values()][:MAX_LINES]


@dataclass
class LineSeen:
    """Что строки одного комментария предложили и что модель увидела на кадрах сверх слов.

    «На кадрах видно ещё» — одно предложение на весь материал, а не по штуке на
    строку: иначе три строки дали бы три одинаковых вопроса. Строка со своими
    словами пункта из этого списка не получает — её пункт решают её слова.
    """

    offered: list[Candidate] = field(default_factory=list)
    also: list[Candidate] = field(default_factory=list)

    def extra(self) -> tuple[Candidate, ...]:
        """Увиденное сверх слов, чего никакая строка уже не предложила."""
        taken = {(c.code, c.zone) for c in self.offered}
        out: dict[tuple[str, str], Candidate] = {}
        for candidate in self.also:
            key = (candidate.code, candidate.zone)
            if key not in taken:
                out.setdefault(key, candidate)
        return tuple(out.values())
