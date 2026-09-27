"""Пересчёт записанной проверки движком — для правки на приёмке (D200).

Вычитывающий исправляет запись (пункт, класс, зону, формулировку), и оценка
обязана пересчитаться: иначе в историю ушла бы буква, посчитанная по другим
записям. Считает только движок, и только по методике ТОЙ версии, которой
проверка помечена, — тем же путём, каким письмо сверяет оценку
(`letters._methodology`). Своей арифметики здесь нет ни строки.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ..db.models import InspectionDetail
from ..domain.models import Score
from ..domain.scoring import parse_score
from . import letters
from .engine_call import AUDIT_SCRIPT
from .engine_call import clean as _clean
from .letters import LetterError, Papers


def rescore(detail: InspectionDetail, *, papers: Papers) -> Score:
    """Оценка проверки такой, какой её посчитает движок по её же методике.

    Отказ — `LetterError` с объяснением: методики той версии нет, движок не
    принял состояние. Молча вернуть прежнюю оценку нельзя: исправленная запись
    с неисправленной буквой выглядела бы пересчитанной.
    """
    каталог, _ = letters._methodology(detail.inspection.checklist_version, papers)
    with tempfile.TemporaryDirectory(prefix="rescore-") as рядом:
        состояние = Path(рядом) / "inspection.json"
        состояние.write_text(
            letters.state_json(detail, lang=detail.inspection.report_lang), encoding="utf-8"
        )
        код, вывод, ошибки = letters._run(
            AUDIT_SCRIPT, ["score", "--json"], data_dir=каталог, state=состояние
        )
        if код != 0:
            raise LetterError(
                "Движок не посчитал исправленную проверку по её методике: "
                f"{_clean(вывод + ошибки, каталог, состояние.parent)}"
            )
    try:
        посчитано: Any = json.loads(вывод)
    except json.JSONDecodeError:
        raise LetterError("Движок ответил на пересчёт не разбираемым JSON") from None
    return parse_score(посчитано)
