"""Чтение для документа предписания: визиты проверок и английские формулировки записей (шаг 3).

Документ собирается из того, что УЖЕ записано: нарушения лежат в
`prescription_findings`, а здесь читается остальное — кто, когда и в какую
точку приезжал (таблица визитов) и английская формулировка записи, если она есть
(`translations`, язык `en`). Охват — как у остальных чтений предписаний: проверка
вне охвата читающего в таблицу не попадает.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from .config import check_environment
from .errors import PrescriptionError
from .pool import connection
from .reach import Reach, require_reach

# Адрес — из справочника сведений о пиццериях по стране и нормализованному имени.
_VISITS_SQL = """
select i.id, u.name, coalesce(up.address, ''), i.inspection_date, i.auditor
from inspections i
join units u on u.id = i.unit_id
left join unit_profiles up
       on up.country_code = u.country and up.name_normalized = u.name_normalized
where i.id = any(%(ids)s::uuid[])
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
order by i.inspection_date, u.name, i.id
"""

_ENGLISH_SQL = """
select t.entity_id, t.text
from translations t
join findings f on f.id = t.entity_id
join inspections i on i.id = f.inspection_id
join units u on u.id = i.unit_id
where t.entity_type = 'finding' and t.field = 'text' and t.lang = 'en'
  and f.inspection_id = %(id)s
  and (%(tenants)s::text[] is null or i.tenant_code = any(%(tenants)s))
  and (%(countries)s::text[] is null or u.country = any(%(countries)s))
"""


@dataclass(frozen=True)
class Visit:
    """Визит проверки: объект строкой (сейчас — пиццерия, ПРЦ и цех теста лягут сюда, D605)."""

    inspection_id: str
    object_name: str
    address: str
    visited_on: date
    visitor: str


def visits(inspection_ids: Sequence[str], *, reach: Reach) -> tuple[Visit, ...]:
    """Визиты проверок-оснований в охвате читающего, по дате."""
    if not inspection_ids:
        return ()
    params = {"ids": list(inspection_ids), **require_reach(reach).params()}
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_VISITS_SQL, params)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise PrescriptionError(
            f"Не удалось прочитать визиты проверок ({type(exc).__name__})"
        ) from exc
    return tuple(
        Visit(
            inspection_id=str(r[0]),
            object_name=str(r[1]),
            address=str(r[2]),
            visited_on=r[3],
            visitor=str(r[4] or ""),
        )
        for r in rows
    )


def english_texts(inspection_id: str, *, reach: Reach) -> dict[str, str]:
    """Английские формулировки записей проверки: идентификатор записи → текст.

    Записи без английской строки в словарь не попадают — документ возьмёт запись
    на языке отчёта, а панель ОСБ скажет «нет перевода».
    """
    params = {"id": inspection_id, **require_reach(reach).params()}
    try:
        with connection(check_environment().dsn) as conn, conn.cursor() as cur:
            cur.execute(_ENGLISH_SQL, params)
            rows = cur.fetchall()
    except psycopg.Error as exc:
        raise PrescriptionError(
            f"Не удалось прочитать формулировки записей ({type(exc).__name__})"
        ) from exc
    return {str(r[0]): str(r[1]) for r in rows if str(r[1]).strip()}
