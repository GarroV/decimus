"""Сборка предписания из проверки в вебе: отбор нарушений, форма, документ PDF (шаг 3, D602, D606).

Модуль соединяет три готовых куска: отбор записей (`report.notice`, движок),
английские формулировки (`db.prescription_notice`) и документ (`report.notice_pdf`).
Нарушения кладутся в предписание снимком; форма показывает галочки и срок по
каждой строке, ОСБ снимает и добавляет любую запись проверки.

Пометка «нет перевода» — только в панели ОСБ: описание записи берётся по-английски,
если английская строка есть, иначе как записано, и это видно человеку, а в
документ пометка не идёт.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from flask import Request

from src.db import prescription_notice as notice_db
from src.db import queries
from src.db.errors import DbError, PrescriptionError
from src.db.prescriptions import FindingPick, NoticeFinding
from src.db.reach import Reach
from src.report import notice as notice_rules
from src.report.errors import ReportError
from src.report.letters import sources as letter_sources

logger = logging.getLogger(__name__)

#: Срок устранения по умолчанию — дата документа плюс столько дней (D602).
DEFAULT_TERM_DAYS = 30

FIELD_SHOWN = "finding_shown"
FIELD_INCLUDED = "finding"
FIELD_DUE_PREFIX = "fdue_"


def default_due(today: date) -> date:
    """Срок устранения по умолчанию (D602): дата документа + 30 дней, правится человеком."""
    return today + timedelta(days=DEFAULT_TERM_DAYS)


@dataclass(frozen=True)
class FormState:
    """Что человек сделал с таблицей нарушений в форме."""

    #: Записи, которые форма показала (для остальных действует предложение правила).
    shown: frozenset[str] = frozenset()
    included: frozenset[str] = frozenset()
    dues: Mapping[str, date] | None = None

    def is_included(self, finding_id: str, *, default: bool) -> bool:
        return (finding_id in self.included) if finding_id in self.shown else default

    def due_of(self, finding_id: str) -> date | None:
        return (self.dues or {}).get(finding_id)


def state_of(request: Request) -> FormState:
    """Состояние таблицы нарушений из тела формы."""
    dues: dict[str, date] = {}
    for key, value in request.form.items():
        if key.startswith(FIELD_DUE_PREFIX):
            try:
                dues[key[len(FIELD_DUE_PREFIX) :]] = date.fromisoformat(value.strip()[:10])
            except ValueError:
                continue
    return FormState(
        shown=frozenset(request.form.getlist(FIELD_SHOWN)),
        included=frozenset(request.form.getlist(FIELD_INCLUDED)),
        dues=dues,
    )


def _description(finding_text: str, lang: str, english: str | None) -> tuple[str, bool]:
    """Описание записи для документа и есть ли оно по-английски (D601)."""
    if english:
        return english, True
    own = (finding_text or "").strip()
    return own, lang == "en" or not own


def assemble(
    inspection_ids: Sequence[str],
    *,
    reach: Reach,
    due: date,
    state: FormState | None = None,
) -> tuple[FindingPick, ...]:
    """Все записи D1–D3 проверок-оснований как строки таблицы предписания.

    Включены те, что предлагает правило (`report.notice.suggest`, D606), если человек
    не решил иначе. Движок не отвечает — `PrescriptionError`: без него нет ни
    английской формулировки пункта, ни зон, обнулённых целиком.
    """
    выбор = state or FormState()
    picks: list[FindingPick] = []
    for inspection_id in inspection_ids:
        try:
            detail = queries.get_inspection(inspection_id, reach=reach)
        except DbError as exc:
            raise PrescriptionError("Не удалось прочитать проверку-основание") from exc
        if detail is None:
            raise PrescriptionError("Проверка-основание недоступна")
        try:
            rows = notice_rules.inspection_candidates(detail, papers=letter_sources())
        except ReportError as exc:
            raise PrescriptionError(f"Нарушения проверки не собраны: {exc}") from exc
        english = notice_db.english_texts(inspection_id, reach=reach)
        by_n = {f.n: f for f in detail.findings}
        for row in rows:
            finding = by_n.get(row.n)
            if finding is None:
                continue
            text, translated = _description(
                finding.text or "", finding.lang, english.get(finding.id)
            )
            picks.append(
                FindingPick(
                    inspection_id=inspection_id,
                    finding_id=finding.id,
                    position=len(picks) + 1,
                    object_name=detail.inspection.unit_name,
                    level=row.level,
                    clause=row.clause,
                    description=text,
                    description_translated=translated,
                    due_on=выбор.due_of(finding.id) or due,
                    engine_due_on=row.engine_due_on,
                    suggested=row.suggested,
                    included=выбор.is_included(finding.id, default=row.suggested),
                )
            )
    return tuple(picks)


def as_rows(picks: Sequence[FindingPick]) -> tuple[NoticeFinding, ...]:
    """Строки формы из кандидатов: те же поля, что у записанных (форма читает одну форму)."""
    return tuple(
        NoticeFinding(
            id=p.finding_id,
            inspection_id=p.inspection_id,
            finding_id=p.finding_id,
            position=p.position,
            object_kind=p.object_kind,
            object_name=p.object_name,
            level=p.level,
            clause=p.clause,
            description=p.description,
            description_translated=p.description_translated,
            due_on=p.due_on,
            engine_due_on=p.engine_due_on,
            suggested=p.suggested,
            included=p.included,
        )
        for p in picks
    )
