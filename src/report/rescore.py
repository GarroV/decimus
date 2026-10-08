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
from collections.abc import Sequence
from dataclasses import dataclass
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


#: Команды движка, которыми правится состав записей загружаемой проверки
#: (D305). Других движку отсюда не передаётся: этот вход — правка записей и
#: только она.
ENGINE_EDITS = frozenset({"add", "edit", "drop"})


@dataclass(frozen=True)
class Applied:
    """Что стало с проверкой после команды движка: оценка и записи, как их видит движок.

    `findings` — записи из файла состояния ПОСЛЕ команды, в форме движка
    (`n`, `qid`, `level`, `zone`, `zone_unusual`, `evidence`, `comment`,
    `repeat`). Отдаются целиком, а не одной новой записью: номер новой записи
    и пометку необычной зоны (D206) назначает движок, и вызывающий берёт их
    отсюда, а не выводит сам.
    """

    score: Score
    findings: tuple[dict[str, Any], ...]


def apply_command(detail: InspectionDetail, *, papers: Papers, args: Sequence[str]) -> Applied:
    """Применить к проверке команду движка (`add`/`edit`/`drop`) и посчитать итог.

    Загрузка исторической проверки (D305) правит записи ТЕМ ЖЕ движком, что и
    бот на обходе: пункт есть в чек-листе версии, класс для него допустим,
    рекомендация — только у пункта-нарушения, зона есть в справочнике версии,
    пара «пункт + зона» свободна (D0 и R её не занимают). Ни одно из этих
    правил здесь не переписано — второй экземпляр разошёлся бы с движком на
    первой же правке методики. Методика — ТОЙ версии, которой помечена
    проверка (`letters._methodology`), как у `rescore`.

    Отказ — `LetterError` с текстом движка (пути вычищены): его и показывают
    человеку, как показывает бот.
    """
    if not args or args[0] not in ENGINE_EDITS:
        raise LetterError(f"Команда движка «{args[0] if args else ''}» здесь не принимается")
    каталог, _ = letters._methodology(detail.inspection.checklist_version, papers)
    with tempfile.TemporaryDirectory(prefix="import-") as рядом:
        состояние = Path(рядом) / "inspection.json"
        состояние.write_text(
            letters.state_json(detail, lang=detail.inspection.report_lang), encoding="utf-8"
        )
        код, вывод, ошибки = letters._run(
            AUDIT_SCRIPT, list(args), data_dir=каталог, state=состояние
        )
        if код != 0:
            raise LetterError(_clean(вывод + ошибки, каталог, состояние.parent))
        код, вывод, ошибки = letters._run(
            AUDIT_SCRIPT, ["score", "--json"], data_dir=каталог, state=состояние
        )
        if код != 0:
            raise LetterError(
                "Движок не посчитал проверку после правки по её методике: "
                f"{_clean(вывод + ошибки, каталог, состояние.parent)}"
            )
        записи: Any = json.loads(состояние.read_text(encoding="utf-8")).get("findings", [])
    try:
        посчитано: Any = json.loads(вывод)
    except json.JSONDecodeError:
        raise LetterError("Движок ответил на пересчёт не разбираемым JSON") from None
    return Applied(
        score=parse_score(посчитано),
        findings=tuple(dict(f) for f in записи if isinstance(f, dict)),
    )
