"""Лимит проверок на пиццерию у пространств партнёров на время теста (D755).

Одно место, через которое идут оба пути заведения строки в `inspections`:
слив из бота (`push._push`) и черновик загрузки (`imports._insert_draft`; им же
пользуются веб и MCP). Считается число проверок точки в пространстве, а решает
чистая `limit_reached` — её проверяет юнит-тест без базы.

Считаются живые проверки: черновики и принятые, у обоих происхождений
`field` и `import`. Не считаются снятые (`retracted_at`), отброшенные черновики
(строка удалена, `imports.discard_draft`) и исторические (`origin = 'legacy'`,
D332) — их место не занимает. Пространство УК лимит не касается.

Лимит — настройка пространства (`space_limits`, `0133`, D759): строки нет — умолчание
5 (`PARTNER_INSPECTIONS_PER_UNIT`), пустое значение — без лимита, число — оно. Правит
управляющая компания на экране «Пространства» (`src/db/space_limits.py`).
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg

from src.domain.space_limits import DEFAULT_INSPECTIONS_PER_UNIT, effective
from src.domain.tenants import HQ_TENANT

from . import space_limits
from .config import check_environment
from .directory import resolve_unit_id
from .errors import DbError, InspectionLimitError
from .pool import connection

logger = logging.getLogger(__name__)

#: Умолчание: сколько проверок на одну пиццерию доступно пространству партнёра, у которого
#: нет своей настройки (D755, владелец 12.11.2026). Пространства УК лимит не касается.
PARTNER_INSPECTIONS_PER_UNIT = DEFAULT_INSPECTIONS_PER_UNIT

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


def limit_reached(
    tenant: str,
    *,
    existing: int,
    origin: str = "field",
    limit: int | None = PARTNER_INSPECTIONS_PER_UNIT,
) -> bool:
    """Решение: нельзя ли заводить ещё одну проверку (чистая функция, без базы).

    `limit` — действующий лимит пространства; `None` — без лимита.
    """
    if is_exempt(tenant, origin) or limit is None:
        return False
    return existing >= limit


def refuse_over_limit(
    cur: Any, *, tenant: str, unit_id: object, unit_name: str, origin: str = "field"
) -> None:
    """Отказ `InspectionLimitError`, если у пиццерии пространства партнёра нет места.

    Зовётся перед вставкой проверки, в той же транзакции. Для УК и для
    исторической загрузки базу не трогает вовсе.
    """
    if is_exempt(tenant, origin):
        return
    limit = effective(tenant, space_limits.stored_in(cur, tenant)).inspections_per_unit
    if limit is None:
        return
    params = {"tenant": tenant, "unit": unit_id}
    cur.execute(_LOCK_SQL, params)
    cur.execute(_COUNT_SQL, params)
    row = cur.fetchone()
    existing = int(row[0]) if row is not None else 0
    if limit_reached(tenant, existing=existing, origin=origin, limit=limit):
        raise InspectionLimitError(unit=unit_name, limit=limit)


def refuse_start_over_limit(tenant: str, unit_name: str) -> None:
    """Ранний отказ на СТАРТЕ проверки: аудитор не обходит пиццерию зря (D755).

    Зовут бот и мини-апп до `start_inspection`. Считает тем же подсчётом, что и
    заслон на вставке (он остаётся последней линией, там же и замок). Сбой базы
    или незнакомая точка старт не останавливают: проверка идёт без базы (D027),
    а точку со справочником сверит слив.
    """
    if is_exempt(tenant, "field"):
        return
    try:
        settings = check_environment()
        with connection(settings.dsn) as conn, conn.cursor() as cur:
            limit = effective(tenant, space_limits.stored_in(cur, tenant)).inspections_per_unit
            unit_id = resolve_unit_id(conn, unit_name, tenant=HQ_TENANT)
            if unit_id is None or limit is None:
                return
            cur.execute(_COUNT_SQL, {"tenant": tenant, "unit": unit_id})
            row = cur.fetchone()
    except (DbError, psycopg.Error) as exc:
        logger.warning("лимит проверок на старте не сверен: %s", exc)
        return
    if limit_reached(tenant, existing=int(row[0]) if row is not None else 0, limit=limit):
        raise InspectionLimitError(unit=unit_name, limit=limit)
