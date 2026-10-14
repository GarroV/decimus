"""Почему оценка такая — ответ движка по записанной проверке (D490).

Карточка проверки показывает рядом с буквой, какое правило её дало, и
расшифровку «от 100 % до итога». Ни того, ни другого карточка не считает:
движок (`audit.py score --json`) отдаёт `grade_rule` и `breakdown` рядом с
оценкой, а здесь они только забираются — по методике ТОЙ версии, которой
проверка помечена, тем же путём, что пересчёт (`rescore`) и письмо.

Сверка обязательна: если движок по этой методике считает не то, что записано в
базе (старые данные, методика переиздана), объяснение не отдаётся вовсе —
показать причину буквы, которой в проверке нет, хуже, чем промолчать. Историческую
проверку (D332) движок не считает, и объяснения у неё нет по определению.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db.models import InspectionDetail
from . import letters
from .engine_call import AUDIT_SCRIPT
from .engine_call import clean as _clean
from .letters import LetterError, Papers
from .rescore import refuse_legacy


@dataclass(frozen=True)
class Explained:
    """Ответ движка «почему»: правило буквы и расшифровка, как они пришли."""

    #: `{"index", "if", "better_if"}` — условие сработавшего правила из `scoring.json`.
    grade_rule: dict[str, Any]
    #: `{"start", "lines", "skipped", "total", "exact"}` — см. `audit.breakdown`.
    breakdown: dict[str, Any]


def explain(detail: InspectionDetail, *, papers: Papers) -> Explained:
    """Правило буквы и расшифровка оценки записанной проверки.

    Отказ — `LetterError`: историческая, методики той версии нет, движок не
    принял состояние или посчитал иначе, чем записано.
    """
    refuse_legacy(detail)
    каталог, _ = letters._methodology(detail.inspection.checklist_version, papers)
    with tempfile.TemporaryDirectory(prefix="explain-") as рядом:
        состояние = Path(рядом) / "inspection.json"
        состояние.write_text(
            letters.state_json(detail, lang=detail.inspection.report_lang), encoding="utf-8"
        )
        код, вывод, ошибки = letters._run(
            AUDIT_SCRIPT, ["score", "--json"], data_dir=каталог, state=состояние
        )
        if код != 0:
            raise LetterError(
                "Движок не посчитал проверку по её методике: "
                f"{_clean(вывод + ошибки, каталог, состояние.parent)}"
            )
    try:
        посчитано: Any = json.loads(вывод)
        правило, разбивка = посчитано["grade_rule"], посчитано["breakdown"]
        pct, grade = float(посчитано["pct"]), str(посчитано["grade"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise LetterError("Движок ответил без правила буквы и расшифровки") from None
    записано = detail.inspection
    if round(pct, 2) != round(записано.pct, 2) or grade != записано.grade:
        raise LetterError(
            f"Движок по методике {записано.checklist_version} считает {pct:g}% {grade}, а в "
            f"проверке записано {записано.pct:g}% {записано.grade}: объяснять нечего"
        )
    return Explained(grade_rule=dict(правило), breakdown=dict(разбивка))
