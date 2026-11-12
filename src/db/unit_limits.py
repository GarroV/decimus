"""Лимит проверок на пиццерию у пространств партнёров на время теста (D755).

Одно место, через которое идут оба пути заведения строки в `inspections`:
слив из бота (`push._push`) и черновик загрузки (`imports._insert_draft`; им же
пользуются веб и MCP). Считается число проверок точки в пространстве, а решает
чистая `limit_reached` — её проверяет юнит-тест без базы.

Считаются живые проверки: черновики и принятые, у обоих происхождений
`field` и `import`. Не считаются снятые (`retracted_at`), отброшенные черновики
(строка удалена, `imports.discard_draft`) и исторические (`origin = 'legacy'`,
D332) — их место не занимает. Пространство УК лимит не касается.

Система лимитов с настройками в админке — отдельно, позже (D755); пока — одна
константа.
"""

from __future__ import annotations

from typing import Any

from src.domain.tenants import HQ_TENANT

from .errors import InspectionLimitError

#: Сколько проверок на одну пиццерию доступно пространству партнёра на время
#: теста (D755, владелец 12.11.2026). Пространства УК лимит не касается.
PARTNER_INSPECTIONS_PER_UNIT = 5

#: Происхождение, которое в счёт не идёт: историческая загрузка (D332).
_UNCOUNTED_ORIGIN = "legacy"

# Замок транзакции — на пару «пространство — точка»: две одновременные вставки
# не должны обе увидеть «4» и обе пройти.
_LOCK_SQL = "select pg_advisory_xact_lock(hashtextextended(%(tenant)s || ':' || %(unit)s::text, 0))"

_COUNT_SQL = """
select count(*) from inspections
where tenant_code = %(tenant)s and unit_id = %(unit)s
  and retracted_at is null and origin <> 'legacy'
"""


def is_exempt(tenant: str, origin: str) -> bool:
    """Лимит не касается пространства УК и исторической загрузки."""
    return tenant == HQ_TENANT or origin == _UNCOUNTED_ORIGIN


def limit_reached(tenant: str, *, existing: int, origin: str = "field") -> bool:
    """Решение: нельзя ли заводить ещё одну проверку (чистая функция, без базы)."""
    if is_exempt(tenant, origin):
        return False
    return existing >= PARTNER_INSPECTIONS_PER_UNIT


def refuse_over_limit(
    cur: Any, *, tenant: str, unit_id: object, unit_name: str, origin: str = "field"
) -> None:
    """Отказ `InspectionLimitError`, если у пиццерии пространства партнёра нет места.

    Зовётся перед вставкой проверки, в той же транзакции. Для УК и для
    исторической загрузки базу не трогает вовсе.
    """
    if is_exempt(tenant, origin):
        return
    params = {"tenant": tenant, "unit": unit_id}
    cur.execute(_LOCK_SQL, params)
    cur.execute(_COUNT_SQL, params)
    row = cur.fetchone()
    existing = int(row[0]) if row is not None else 0
    if limit_reached(tenant, existing=existing, origin=origin):
        raise InspectionLimitError(unit=unit_name, limit=PARTNER_INSPECTIONS_PER_UNIT)
