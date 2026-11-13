"""Та же проверка, заведённая второй раз с другой датой (#1635).

Ключ визита при загрузке — точка и дата (`imports._refuse_same_visit`, #782), и он
не ловит проверку, которую сначала сохранили с неверной датой, а потом завели
заново с верной вместо `move_inspection`: даты разные, содержимое то же слово в
слово. В аналитике такая точка считается дважды — удваиваются буквы, число
нарушений сети и повторы (`repeat`) срабатывают на саму же проверку.

Дубль — это принятая и не снятая проверка той же точки того же пространства в
пределах `DUPLICATE_WINDOW_DAYS` дней с тем же процентом, той же буквой и тем же
набором записей (пункт, класс, зона, текст). Пустая проверка дублем не считается:
две чистые проверки подряд — обычная жизнь, а не повтор. Решает набор записей, а
не одна оценка: две разные проверки с одним процентом встречаются.

Проверка идёт при подтверждении загруженного черновика (`accept.py`), потому что
записи к черновику добавляются после его создания.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

#: Окно сравнения вокруг даты черновика. Случай из задачи — неделя; две недели
#: покрывают «сохранили не в ту неделю» и не лезут в соседний плановый визит.
DUPLICATE_WINDOW_DAYS = 14

_CANDIDATES_SQL = """
select o.id::text, o.inspection_date
from inspections o
     join inspections me on me.id = %(id)s
where o.unit_id = me.unit_id
  and o.tenant_code = me.tenant_code
  and o.id <> me.id
  and o.status = 'finalized'
  and o.retracted_at is null
  and o.inspection_date between me.inspection_date - %(days)s::int
                            and me.inspection_date + %(days)s::int
  and o.pct is not distinct from me.pct
  and o.grade is not distinct from me.grade
order by o.inspection_date, o.pushed_at
"""

_FINDINGS_SQL = """
select f.code, f.level, f.zone, coalesce(t.text, '')
from findings f
     join inspections i on i.id = f.inspection_id
     left join translations t
            on t.entity_type = 'finding' and t.entity_id = f.id
           and t.field = 'text' and t.lang = i.speech_lang
where f.inspection_id = %(id)s
"""

Signature = tuple[tuple[str, str, str, str], ...]


def signature(rows: Iterable[tuple[str, str, str, str]]) -> Signature:
    """Набор записей без порядка: (пункт, класс, зона, текст)."""
    return tuple(sorted((code, level, zone, text.strip()) for code, level, zone, text in rows))


def same_findings(left: Signature, right: Signature) -> bool:
    """Одинаковый непустой набор записей. Пустой набор дублем не считается."""
    return bool(left) and left == right


def find_duplicate(cur: Any, inspection_id: str) -> tuple[str, date] | None:
    """Принятая проверка, повторяющая эту, — `(id, дата)`, либо `None`."""
    cur.execute(_FINDINGS_SQL, {"id": inspection_id})
    own = signature(tuple(r) for r in cur.fetchall())
    if not own:
        return None
    cur.execute(_CANDIDATES_SQL, {"id": inspection_id, "days": DUPLICATE_WINDOW_DAYS})
    candidates = cur.fetchall()
    for other_id, other_day in candidates:
        cur.execute(_FINDINGS_SQL, {"id": other_id})
        if same_findings(own, signature(tuple(r) for r in cur.fetchall())):
            return str(other_id), other_day
    return None
