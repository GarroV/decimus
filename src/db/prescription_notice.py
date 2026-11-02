"""Чтение для сборки предписания: английские формулировки записей проверки (шаг 3).

Нарушения лежат в `prescription_findings` как их согласовали; здесь читается
английская формулировка записи, если она есть (`translations`, язык `en`). Охват —
как у остальных чтений предписаний: проверка вне охвата читающего не читается.
"""

from __future__ import annotations

import psycopg

from .config import check_environment
from .errors import PrescriptionError
from .pool import connection
from .reach import Reach, require_reach

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
