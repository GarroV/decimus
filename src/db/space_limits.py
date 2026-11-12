"""Лимиты пространства партнёра в базе (D759, `0133`): чтение, правка, расход за месяц.

Правило (умолчания, три состояния значения, HQ) — `src/domain/space_limits.py`; здесь
только хранение. Читает роль приложения (бот, слив, загрузка, проверка потолка расхода),
пишет администратор истории — той же узкой ролью, что заведение пространства
(`web_access._managing`). Кто имеет право нажать «Сохранить», решает веб-маршрут.

Расход за месяц — функция `model_usage_spend` (у роли приложения на `model_usage` только
`insert`): суммы по моделям одного пространства с начала календарного месяца UTC. Деньги
считает вызывающий по `model_prices.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.domain.space_limits import Limits, check_inspections, check_spend, is_hq
from src.domain.tenants import canonical_tenant

from .config import check_environment
from .errors import AccessError
from .pool import connection
from .web_access import _managing

_STORED_SQL = """
select inspections_per_unit, monthly_spend_usd from space_limits where tenant_code = %s
"""
_ALL_SQL = """
select tenant_code, inspections_per_unit, monthly_spend_usd, updated_by, updated_at
  from space_limits
"""
_UPSERT_SQL = """
insert into space_limits (tenant_code, inspections_per_unit, monthly_spend_usd, updated_by)
values (%(tenant)s, %(per_unit)s, %(spend)s, %(by)s)
on conflict (tenant_code) do update
   set inspections_per_unit = excluded.inspections_per_unit,
       monthly_spend_usd = excluded.monthly_spend_usd,
       updated_by = excluded.updated_by,
       updated_at = now()
"""
_SPEND_SQL = "select * from model_usage_spend(%s, %s)"
_EXISTS_SQL = "select 1 from tenants where code = %s"


@dataclass(frozen=True)
class StoredLimits:
    """Строка настроек: значения и кто менял."""

    limits: Limits
    updated_by: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class SpendRow:
    """Расход пространства по одной модели за период."""

    model: str
    input_tokens: int
    output_tokens: int
    audio_seconds: float


def _limits(row: Any) -> Limits:
    return Limits(
        inspections_per_unit=None if row[0] is None else int(row[0]),
        monthly_spend_usd=None if row[1] is None else Decimal(row[1]),
    )


def stored_in(cur: Any, tenant: str) -> Limits | None:
    """Строка настроек пространства внутри открытой транзакции; `None` — строки нет."""
    cur.execute(_STORED_SQL, (canonical_tenant(tenant),))
    row = cur.fetchone()
    return None if row is None else _limits(row)


def stored(tenant: str) -> Limits | None:
    """Строка настроек пространства (роль приложения); `None` — строки нет."""
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        return stored_in(cur, tenant)


def stored_all() -> dict[str, StoredLimits]:
    """Все строки настроек по коду пространства — для перечня на экране."""
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_ALL_SQL)
        rows = cur.fetchall()
    return {
        str(r[0]): StoredLimits(
            limits=Limits(
                inspections_per_unit=None if r[1] is None else int(r[1]),
                monthly_spend_usd=None if r[2] is None else Decimal(r[2]),
            ),
            updated_by=None if r[3] is None else str(r[3]),
            updated_at=r[4],
        )
        for r in rows
    }


def month_spend(tenant: str, since: datetime) -> tuple[SpendRow, ...]:
    """Расход модели пространства с `since` по моделям (токены и секунды звука)."""
    with connection(check_environment().dsn) as conn, conn.cursor() as cur:
        cur.execute(_SPEND_SQL, (canonical_tenant(tenant), since))
        rows = cur.fetchall()
    return tuple(
        SpendRow(
            model=str(r[0]),
            input_tokens=int(r[1]),
            output_tokens=int(r[2]),
            audio_seconds=float(r[3] or 0),
        )
        for r in rows
    )


def set_limits(
    tenant: str, *, inspections_per_unit: int | None, monthly_spend_usd: Decimal | None, by: str
) -> Limits:
    """Записать лимиты пространства партнёра. Негодное значение или УК — `AccessError`."""
    код = canonical_tenant(tenant)
    if is_hq(код):
        raise AccessError("У пространства УК лимитов нет: оно не ограничено")
    try:
        проверок = check_inspections(inspections_per_unit)
        потолок = check_spend(monthly_spend_usd)
    except ValueError as exc:
        raise AccessError(
            f"Лимит «{exc}» не годится: проверки — целое от 1, потолок — от 0 с копейками"
        ) from exc
    with _managing(f"изменить лимиты «{код}»") as conn, conn.cursor() as cur:
        cur.execute(_EXISTS_SQL, (код,))
        if cur.fetchone() is None:
            raise AccessError(f"Пространство «{tenant}» не заведено")
        cur.execute(
            _UPSERT_SQL,
            {"tenant": код, "per_unit": проверок, "spend": потолок, "by": by[:120]},
        )
    return Limits(inspections_per_unit=проверок, monthly_spend_usd=потолок)
