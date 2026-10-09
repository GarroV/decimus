"""Записи исторической проверки (`origin = 'legacy'`, D332): без движка.

Историческая — проверка по прежней методике из старого отчёта: её оценка
перенесена как есть и не меняется (D332). Поэтому здесь нет ни `apply`, ни
`apply_score`: движок не зовётся ни на одном пути. Замок берётся тем же
`_locked_detail`, что у текущей, но с `mode=ORIGIN_LEGACY` — черновик текущей
(`import`) сюда не пройдёт, как историческая не пройдёт в путь с движком.

Записи описательные: формулировка обязательна, код пункта, класс и зона — если
отчёт их назвал, иначе маркеры (`models.LEGACY_CODE`, `NO_CLASS`, `NO_ZONE`).
Пара «пункт + зона» не сверяется: в прежней методике её правила могли быть
другими, а запись — пересказ отчёта. `counts` — счёт записей по классам, не оценка.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from .errors import HistoryImportError
from .imports import (
    _INSERT_FINDING_SQL,
    _UPDATE_FINDING_SQL,
    Wording,
    _check_room,
    _check_wording,
    _connect,
    _delete_finding,
    _finding_by_n,
    _locked_detail,
    _refused,
    _write_wording,
)
from .models import LEGACY_CODE, NO_CLASS, NO_ZONE, ORIGIN_LEGACY
from .queries import _require_inspection_id, _require_tenant

#: Классы, которые историческая запись может нести, если отчёт их назвал.
LEGACY_LEVELS = frozenset({"D1", "D2", "D3"})


#: Код пункта и зона исторической записи — коды, а не формулировки.
MAX_LEGACY_CODE = 32


# Счёт записей исторической по классам — НЕ оценка: ни вычетов, ни букв, ни
# разбивки по зонам. Кладётся в `counts`, чтобы читатели, считающие классы по
# этой колонке, видели исторические записи; «без класса» лежит под `NC`.
_LEGACY_COUNTS_SQL = """
update inspections
set counts = coalesce(
    (select jsonb_object_agg(level, cnt)
       from (select level, count(*) as cnt from findings
             where inspection_id = %(id)s group by level) s),
    '{}'::jsonb)
where id = %(id)s and tenant_code = %(tenant)s and origin = 'legacy' and status = 'draft'
"""


@dataclass(frozen=True)
class LegacyFinding:
    """Запись исторической проверки: что старый отчёт назвал, то и лежит (D332).

    `None` у кода, класса и зоны — «отчёт не назвал», ложится маркером.
    """

    code: str | None
    level: str | None
    zone: str | None
    repeat: bool = False


def add_legacy_finding(
    inspection_id: str, *, tenant: str, finding: LegacyFinding, wording: Wording
) -> int:
    """Добавить описательную запись в исторический черновик; вернуть её номер.

    Движок не зовётся: оценка исторической — из старого отчёта и не меняется
    (D332). Номер — следующий за наибольшим. Пара «пункт + зона» не сверяется:
    в старой методике её правила могли быть другими, а запись — пересказ отчёта.
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    if not (wording.text or "").strip():
        raise HistoryImportError("Формулировка записи пуста — запись без слов в отчёт не идёт")
    _check_wording(wording)
    поля = _legacy_fields(finding)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code, mode=ORIGIN_LEGACY)
            _check_room(detail)
            n = max((f.n for f in detail.findings), default=0) + 1
            cur.execute(_INSERT_FINDING_SQL, {"id": ident, "n": n, **поля})
            row = cur.fetchone()
            if row is None:
                raise HistoryImportError("Postgres не вернул строку записи после вставки")
            _write_wording(cur, str(row[0]), ident, wording)
            _write_legacy_counts(cur, ident, tenant_code)
            conn.commit()
            return n
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Добавить запись") from exc


def edit_legacy_finding(
    inspection_id: str, n: int, *, tenant: str, finding: LegacyFinding, wording: Wording
) -> None:
    """Исправить запись исторического черновика по номеру — целиком, без движка.

    `finding` — запись, какой она станет (вызывающий сливает правку с прежней).
    """
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    if wording.text is not None and not wording.text.strip():
        raise HistoryImportError("Формулировка записи пуста — запись без слов в отчёт не идёт")
    _check_wording(wording)
    поля = _legacy_fields(finding)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code, mode=ORIGIN_LEGACY)
            прежняя = _finding_by_n(detail, n)
            cur.execute(_UPDATE_FINDING_SQL, {"id": ident, "finding": прежняя, "n": n, **поля})
            if cur.rowcount != 1:
                raise HistoryImportError(f"Запись #{n} не исправлена — ничего не записано")
            _write_wording(cur, прежняя, ident, wording)
            _write_legacy_counts(cur, ident, tenant_code)
            conn.commit()
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Исправить запись") from exc


def remove_legacy_finding(inspection_id: str, n: int, *, tenant: str) -> tuple[str, ...]:
    """Снять запись с исторического черновика; вернуть ссылки её кадров. Без движка."""
    ident = _require_inspection_id(inspection_id)
    tenant_code = _require_tenant(tenant)
    try:
        with _connect() as conn, conn.cursor() as cur:
            detail = _locked_detail(cur, ident, tenant_code, mode=ORIGIN_LEGACY)
            запись = _finding_by_n(detail, n)
            кадры = _delete_finding(cur, ident, запись, n)
            _write_legacy_counts(cur, ident, tenant_code)
            conn.commit()
            return кадры
    except HistoryImportError:
        raise
    except psycopg.Error as exc:
        raise _refused(exc, "Снять запись") from exc


def _legacy_fields(finding: LegacyFinding) -> dict[str, object]:
    """Поля исторической записи в колонки `findings`; не названное — маркером."""
    код = (finding.code or "").strip().upper() or LEGACY_CODE
    класс = (finding.level or "").strip().upper() or NO_CLASS
    зона = (finding.zone or "").strip() or NO_ZONE
    if len(код) > MAX_LEGACY_CODE or len(зона) > MAX_LEGACY_CODE:
        raise HistoryImportError(f"Код пункта и зона — коды не длиннее {MAX_LEGACY_CODE} знаков")
    if класс != NO_CLASS and класс not in LEGACY_LEVELS:
        raise HistoryImportError(
            f"Класс исторической записи — D1, D2 или D3, либо не назван вовсе («без класса»). "
            f"«{finding.level}» не принимается"
        )
    return {
        "code": код,
        "level": класс,
        "zone": зона,
        "zone_unusual": False,
        "repeat": bool(finding.repeat),
    }


def _write_legacy_counts(cur: Any, ident: str, tenant: str) -> None:
    cur.execute(_LEGACY_COUNTS_SQL, {"id": ident, "tenant": tenant})
    if cur.rowcount != 1:
        raise HistoryImportError(
            "Счёт записей не обновлён: черновик перестал ждать подтверждения — ничего не записано"
        )
