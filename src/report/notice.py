"""Отбор нарушений для предписания по проверке (D602, D606, шаг 3 спеки 2026-10-21).

Ядро: данные, которые партнёр прочтёт как факт. Оценку и зоны считает только
движок (`engine/audit.py score --json`, подпроцессом, как у письма и пересчёта):
здесь ничего не пересчитывается, а только читается его ответ — какие записи есть
и какие зоны обнулены.

Кандидатами служат все записи классов D1–D3 проверки: ОСБ снимает и добавляет
любую галочками. Предложение — одна функция, `suggest` (D606).
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..db.models import InspectionDetail
from . import letters
from .engine_call import AUDIT_SCRIPT
from .engine_call import clean as _clean
from .letters import LetterError, Papers

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


def suggest(score: Mapping[str, Any]) -> frozenset[int]:
    """Номера записей, которые предписание берёт по умолчанию (D602, D606).

    Все записи D3 и все нарушения зон, обнулённых целиком. Зоны — из ответа
    движка (`zones[...]["zeroed"]`), своей арифметики нет.
    """
    # D606: обнуление набором D1 донастроить по методике (движок сейчас отмечает
    # zeroed только по D3 — так и оставлено).
    zeroed = {code for code, zone in (score.get("zones") or {}).items() if zone.get("zeroed")}
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


def engine_score(detail: InspectionDetail, *, papers: Papers) -> dict[str, Any]:
    """Ответ `score --json` по записанной проверке, по её же методике.

    Историческая проверка (D332) не пересчитывается — `LetterError`: для неё нет
    ни пунктов на английском, ни обнулённых зон.
    """
    if detail.inspection.is_legacy:
        raise LetterError(
            "Проверка историческая: её записи в предписание автоматически не собираются (D332)"
        )
    каталог, _ = letters._methodology(detail.inspection.checklist_version, papers)
    with tempfile.TemporaryDirectory(prefix="notice-") as рядом:
        состояние = Path(рядом) / "inspection.json"
        состояние.write_text(
            letters.state_json(detail, lang=detail.inspection.report_lang), encoding="utf-8"
        )
        код, вывод, ошибки = letters._run(
            AUDIT_SCRIPT, ["score", "--json"], data_dir=каталог, state=состояние
        )
        if код != 0:
            raise LetterError(
                "Движок не посчитал проверку для предписания: "
                f"{_clean(вывод + ошибки, каталог, состояние.parent)}"
            )
    try:
        result = json.loads(вывод)
    except json.JSONDecodeError:
        raise LetterError("Движок ответил не разбираемым JSON — предписание не собрано") from None
    if not isinstance(result, dict):
        raise LetterError("Движок ответил не объектом — предписание не собрано")
    return result


def inspection_candidates(detail: InspectionDetail, *, papers: Papers) -> tuple[Candidate, ...]:
    """Кандидаты проверки: записи D1–D3 с предложением правила."""
    return candidates(engine_score(detail, papers=papers))
