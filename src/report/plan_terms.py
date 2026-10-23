"""Сроки и формулировки строк экшн-плана — только из ответа движка (#1168, CLAUDE.md).

«Проценты, буква, разбивка по зонам, сроки — только через `engine/audit.py score`»:
дни на устранение записи (дни пункта методики, не больше потолка класса, D3 —
немедленно) считает движок и кладёт в `findings[].days`. Здесь свой расчёт не
заводится — берётся готовое по методике ТОЙ версии, которой помечена проверка
(`rescore.engine_output`), и разбирается в условия строк. Расхождение с движком
невозможно по построению; пункт, которого нет в методике, у движка даёт ноль дней, и
этот ноль строка плана получает как есть.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from ..db.errors import ActionPlanError
from ..db.models import InspectionDetail
from ..db.plan_rows import FindingTerms, TermsProvider
from .letters import LetterError, Papers
from .rescore import engine_output

#: Класс в формулировке пункта — «(D1)» в конце или «(D1, D2)» в начале: в строке плана он лишний.
_LEVELS = r"\(\s*D\d(?:\s*,\s*D\d)*\s*\)"
_LEVEL_AFFIX = re.compile(rf"^{_LEVELS}\s*|\s*{_LEVELS}$")


def _title(raw: object) -> str:
    return _LEVEL_AFFIX.sub("", str(raw or "")).strip()


def finding_terms(detail: InspectionDetail, *, papers: Papers) -> dict[int, FindingTerms]:
    """Номер записи → условия строки: дни и формулировка пункта, как их отдал движок.

    Отказ движка или методики — `LetterError` (его переводит `provider` в отказ плана).
    """
    out = engine_output(detail, papers=papers)
    terms: dict[int, FindingTerms] = {}
    for item in out.get("findings") or []:
        terms[int(item["n"])] = _terms(item)
    return terms


def _terms(item: Mapping[str, Any]) -> FindingTerms:
    return FindingTerms(
        days=int(item.get("days") or 0),
        title_ru=_title(item.get("question_ru")),
        title_en=_title(item.get("question_en")),
    )


def provider(load: Callable[[str], InspectionDetail | None], *, papers: Papers) -> TermsProvider:
    """Поставщик условий для блока `db`: проверку читает `load`, считает движок.

    Нет проверки или движок не принял — `ActionPlanError` с понятной причиной: блок
    `db` показывает её как отказ запроса плана, а не как поломку.
    """

    def terms_for(inspection_id: str) -> Mapping[int, FindingTerms]:
        detail = load(inspection_id)
        if detail is None:
            raise ActionPlanError("Проверка для условий строк плана не прочитана")
        try:
            return finding_terms(detail, papers=papers)
        except LetterError as exc:
            raise ActionPlanError(f"Сроки записей от движка не получены: {exc}") from exc

    return terms_for
