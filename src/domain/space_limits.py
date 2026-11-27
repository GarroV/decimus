"""Лимиты пространства партнёра (D755, D759 п.5): правило без базы и сети.

Два лимита: сколько проверок на пиццерию и сколько долларов расхода модели в
календарный месяц (UTC). Значения по умолчанию заданы продуктом (D759): 5 проверок
и 50 $; управляющая компания правит их на пространство в «Администрировании».

Три состояния значения: **нет строки настроек** — действует умолчание; **строка с
пустым значением** (`None`) — лимита нет вовсе; **число** — оно и действует.
Пространство УК лимитов не имеет никогда, что бы ни лежало в таблице.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from .tenants import HQ_TENANT, canonical_tenant

#: Проверок на пиццерию у партнёра по умолчанию (D755, владелец 12.11.2026).
DEFAULT_INSPECTIONS_PER_UNIT = 5
#: Потолок расхода модели у партнёра в месяц, $, по умолчанию (D759: замер ≈1 $ на проверку,
#: максимум 3,25 $ — 50 $ покрывают пять пиццерий по пять проверок с запасом).
DEFAULT_MONTHLY_SPEND_USD = Decimal("50")
#: С какой доли потолка экран предупреждает администратора.
WARN_SHARE = Decimal("0.8")

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_OVER = "over"


@dataclass(frozen=True)
class Limits:
    """Действующие лимиты пространства; `None` — без лимита."""

    inspections_per_unit: int | None
    monthly_spend_usd: Decimal | None


#: Лимиты пространства УК и любого, кому лимит снят: ничем не ограничено.
UNLIMITED = Limits(inspections_per_unit=None, monthly_spend_usd=None)
#: Лимиты партнёра, у которого строки настроек нет.
DEFAULTS = Limits(
    inspections_per_unit=DEFAULT_INSPECTIONS_PER_UNIT,
    monthly_spend_usd=DEFAULT_MONTHLY_SPEND_USD,
)


def is_hq(tenant: str) -> bool:
    return canonical_tenant(tenant) == HQ_TENANT


def effective(tenant: str, stored: Limits | None) -> Limits:
    """Лимиты, которые действуют: УК — никаких; нет строки — умолчания; иначе строка."""
    if is_hq(tenant):
        return UNLIMITED
    return DEFAULTS if stored is None else stored


def month_start(now: datetime) -> datetime:
    """Начало календарного месяца (UTC), в котором лежит `now`."""
    moment = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spend_level(spent: Decimal, cap: Decimal | None) -> str:
    """`over` — потолок достигнут, `warn` — от 80 % потолка, иначе `ok`; нет потолка — `ok`."""
    if cap is None:
        return LEVEL_OK
    if spent >= cap:
        return LEVEL_OVER
    if cap > 0 and spent >= cap * WARN_SHARE:
        return LEVEL_WARN
    return LEVEL_OK


def check_inspections(value: int | None) -> int | None:
    """Годный лимит проверок: целое от 1 или `None`; иначе `ValueError`."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("inspections_per_unit")
    return value


def check_spend(value: Decimal | None) -> Decimal | None:
    """Годный потолок расхода: от 0 (модель выключена) до миллиона, с копейками, или `None`."""
    if value is None:
        return None
    if value < 0 or value > Decimal("1000000") or value != value.quantize(Decimal("0.01")):
        raise ValueError("monthly_spend_usd")
    return value
