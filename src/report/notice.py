"""Отбор нарушений для предписания по проверке (D602, D606, шаг 3 спеки 2026-10-21).

Ядро: данные, которые партнёр прочтёт как факт. Оценку и зоны считает только
движок (`engine/audit.py score --json`, `rescore.engine_output` — тот же вход, что у пересчёта):
здесь ничего не пересчитывается, а только читается его ответ — какие записи есть
и какие зоны обнулены.

Кандидатами служат все записи классов D1–D3 проверки: ОСБ снимает и добавляет
любую галочками. Предложение — одна функция, `suggest` (D606).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..db.models import InspectionDetail
from . import rescore
from .letters import Papers

#: Классы записей, которые бывают нарушением. Рекомендации и информационные
#: записи (`R`, `D0`) в предписание не идут.
VIOLATION_LEVELS = frozenset({"D1", "D2", "D3"})

_CLASS_MARK = re.compile(
    r"^\s*\(\s*D[0-9](\s*,\s*D[0-9])*\s*\)\s*|\s*\(\s*D[0-9](\s*,\s*D[0-9])*\s*\)\s*$"
)


@dataclass(frozen=True)
class Candidate:
    """Запись проверки как строка таблицы предписания, до выбора человека."""

    n: int
    level: str
    zone: str
    #: Формулировка пункта чек-листа той версии, по-английски (иначе русская).
    clause: str
    #: Срок пункта по движку (подсказка рядом с датой предписания).
    engine_due_on: date | None
    #: Предложено правилом `suggest`.
    suggested: bool


def zeroed_zones(score: Mapping[str, Any]) -> frozenset[str]:
    """Зоны, которые движок отдаёт обнулёнными: флаг `zeroed` (D3) или остаток зоны 0 (набор D1).

    Остаток читается из ответа движка (`zones[...]["score"]` при положительной доле):
    движок уже вычел штрафы по ставкам методики, своей арифметики здесь нет.
    """
    zones = score.get("zones") or {}
    return frozenset(
        code
        for code, zone in zones.items()
        if zone.get("zeroed")
        or (float(zone.get("share") or 0) > 0 and float(zone.get("score", 1)) <= 0)
    )


def suggest(score: Mapping[str, Any]) -> frozenset[int]:
    """Номера записей, которые предписание берёт по умолчанию (D602, D606).

    Все записи D3 и все нарушения зон, обнулённых целиком — D3 или набором D1
    (`zeroed_zones`). Правило расширяемое (D610): новые основания — новые зоны здесь.
    """
    zeroed = zeroed_zones(score)
    return frozenset(
        int(item["n"])
        for item in score.get("findings") or []
        if item.get("level") == "D3"
        or (item.get("level") in VIOLATION_LEVELS and item.get("zone") in zeroed)
    )


def _clause(item: Mapping[str, Any]) -> str:
    text = str(item.get("question_en") or item.get("question_ru") or "")
    return _CLASS_MARK.sub("", text).strip() or str(item.get("qid") or "")


def candidates(score: Mapping[str, Any]) -> tuple[Candidate, ...]:
    """Все записи D1–D3 из ответа движка по номеру записи, с отметкой «предложено»."""
    предложено = suggest(score)
    rows: list[Candidate] = []
    for item in score.get("findings") or []:
        if item.get("level") not in VIOLATION_LEVELS:
            continue
        due = str(item.get("due") or "")
        rows.append(
            Candidate(
                n=int(item["n"]),
                level=str(item["level"]),
                zone=str(item.get("zone") or ""),
                clause=_clause(item),
                engine_due_on=date.fromisoformat(due) if due else None,
                suggested=int(item["n"]) in предложено,
            )
        )
    return tuple(sorted(rows, key=lambda c: c.n))


def inspection_candidates(detail: InspectionDetail, *, papers: Papers) -> tuple[Candidate, ...]:
    """Кандидаты проверки: записи D1–D3 с предложением правила."""
    return candidates(rescore.engine_output(detail, papers=papers))
