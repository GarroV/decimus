"""Журнал правок записей проверки на приёмке (F-134, `0081`).

Правит вычитывающий — и управляющая компания, и партнёр (D341, D367): правка не
ограничивается, но каждая оставляет след — кто, когда и что именно изменилось
(поле, старое и новое значение, оценка до и после). Запись в журнал идёт ТОЙ ЖЕ
транзакцией, что и правка: вызывающий отдаёт сюда свой курсор и коммитит один раз.
Правки без следа не бывает, и следа без правки тоже.

Модуль только формирует и пишет строку; решений не принимает и правку не блокирует.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from psycopg.types.json import Json

from ..domain.models import Score
from .models import FindingRow, InspectionDetail

EditKind = Literal["revise", "add", "delete"]

_INSERT_SQL = """
insert into inspection_edits
    (inspection_id, finding_id, tenant_code, user_id, login, role, kind, changes)
values (%(inspection)s, %(finding)s, %(tenant)s, %(user)s, %(login)s, %(role)s, %(kind)s,
        %(changes)s)
"""


@dataclass(frozen=True)
class Editor:
    """Кто правит: учётка админки, как её опознала сессия."""

    user_id: str
    login: str
    role: str


def _pair(old: object, new: object) -> dict[str, object]:
    return {"old": old, "new": new}


def finding_changes(old: FindingRow | None, new: Mapping[str, object]) -> dict[str, Any]:
    """Поля записи, у которых значение стало другим: `{поле: {"old", "new"}}`.

    `old=None` — запись заводится заново: старого значения нет, у каждого поля `old` пуст.
    """
    прежние: Mapping[str, object] = (
        {}
        if old is None
        else {
            "code": old.code,
            "level": old.level,
            "zone": old.zone,
            "zone_unusual": old.zone_unusual,
            "text": (old.text or "").strip(),
            "reading_c": old.reading_c,
        }
    )
    return {
        поле: _pair(прежние.get(поле), значение)
        for поле, значение in new.items()
        if old is None or прежние.get(поле) != значение
    }


def finding_removal(old: FindingRow) -> dict[str, Any]:
    """Запись снята: у каждого поля прежнее значение и пустое новое (`new: None`)."""
    return {
        "code": _pair(old.code, None),
        "level": _pair(old.level, None),
        "zone": _pair(old.zone, None),
        "zone_unusual": _pair(old.zone_unusual, None),
        "text": _pair((old.text or "").strip(), None),
        "reading_c": _pair(old.reading_c, None),
    }


def score_changes(old: InspectionDetail, new: Score) -> dict[str, Any]:
    """Оценка до и после: процент, буква и вычеты — то, что читают как факт."""
    return {
        "score_pct": _pair(old.inspection.pct, new.pct),
        "score_grade": _pair(old.inspection.grade, new.grade),
        "score_deductions": _pair(old.deductions, new.deductions),
    }


def record_edit(
    cur: Any,
    *,
    inspection_id: str,
    finding_id: str,
    tenant: str,
    editor: Editor,
    kind: EditKind,
    changes: Mapping[str, Any],
) -> None:
    """Дописать строку правки на курсоре правки — в её транзакции, без собственного коммита."""
    cur.execute(
        _INSERT_SQL,
        {
            "inspection": inspection_id,
            "finding": finding_id,
            "tenant": tenant,
            "user": editor.user_id,
            "login": editor.login,
            "role": editor.role,
            "kind": kind,
            "changes": Json(dict(changes)),
        },
    )
