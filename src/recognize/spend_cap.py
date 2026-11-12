"""Потолок расхода модели на пространство в месяц (D759 п.5, #1670).

Единственная точка вызова провайдера (`client.ask_model`, `transcribe.transcribe`) зовёт
`ensure_within_cap` ДО платного запроса: расход пространства с начала календарного месяца
(UTC) уже не меньше потолка — вызова нет, человек получает `ModelLimitReached`, а ручной
ввод без модели продолжается. Пространство берётся из контекста обращения
(`domain.model_usage.current_scope`): дверь, не назвавшая пространства (служебный вызов,
замер), не проверяется. Пространство УК потолка не имеет никогда.

**Расход — оценка по `model_prices.json`**, та же, что на экране «Расход модели»: модель без
цены в сумму не входит (потолок её не видит — цену нужно завести вместе с моделью), кэш
провайдера не вычитается (оценка сверху, не снизу).

**Стоит дёшево:** лимиты и сумма читаются одним запросом каждый (сумма — агрегат по индексу
`model_usage_tenant_time_idx`) и кэшируются на `CACHE_SECONDS` на процесс. Гонку «два вызова
одновременно на границе» допускаем: превышение потолка на один-два вызова терпимо (вызов
стоит ≈1 $ при потолке в десятки), поэтому замка нет. Сбой базы вызов не останавливает —
проверка открывается (в журнал), как и учёт расхода: потолок не вправе ронять работу.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import psycopg

from src.db import space_limits
from src.db.errors import AccessError, DbError
from src.domain.model_usage import current_scope
from src.domain.space_limits import (
    LEVEL_OVER,
    effective,
    is_hq,
    month_start,
    spend_level,
)
from src.domain.tenants import canonical_tenant

from .errors import ModelLimitReached
from .pricing import Price, estimate_cost

logger = logging.getLogger(__name__)

#: Сколько секунд в процессе держится прочитанное. Превышение за это время — на нескольких
#: вызовах подряд, а не на сотнях: цена вызова ≈1 $, потолок — десятки.
CACHE_SECONDS = 10.0

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class Spend:
    """Расход пространства за месяц и его потолок."""

    spent: Decimal
    #: Часть расхода — по моделям без цены: сумма неполная.
    partial: bool
    cap: Decimal | None

    @property
    def level(self) -> str:
        return spend_level(self.spent, self.cap)


def cost_of(
    rows: tuple[space_limits.SpendRow, ...], prices: dict[str, Price] | None = None
) -> tuple[Decimal, bool]:
    """Оценка в долларах по строкам расхода и признак «были модели без цены»."""
    total = Decimal(0)
    partial = False
    for r in rows:
        one = estimate_cost(
            r.model,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            audio_seconds=r.audio_seconds,
            prices=prices,
        )
        if one is None:
            partial = partial or bool(r.input_tokens or r.output_tokens or r.audio_seconds)
        else:
            total += Decimal(repr(one))
    return total.quantize(_CENTS), partial


def month_spend(tenant: str, *, now: datetime | None = None) -> Spend:
    """Расход пространства с начала месяца и его потолок. Ошибки базы — вызывающему."""
    код = canonical_tenant(tenant)
    moment = now or datetime.now(UTC)
    cap = effective(код, space_limits.stored(код)).monthly_spend_usd
    spent, partial = cost_of(space_limits.month_spend(код, month_start(moment)))
    return Spend(spent=spent, partial=partial, cap=cap)


_lock = threading.Lock()
_cache: dict[str, tuple[float, Spend]] = {}


def forget() -> None:
    """Сбросить кэш: после правки лимита и в тестах."""
    with _lock:
        _cache.clear()


def _cached(
    tenant: str, *, clock: Callable[[], float], read: Callable[[str], Spend]
) -> Spend | None:
    now = clock()
    with _lock:
        hit = _cache.get(tenant)
        if hit is not None and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        fresh = read(tenant)
    except (DbError, AccessError, psycopg.Error, OSError) as exc:
        logger.warning("потолок расхода модели не сверен (%s): вызов идёт", type(exc).__name__)
        return None
    with _lock:
        _cache[tenant] = (now, fresh)
    return fresh


def ensure_within_cap(
    tenant: str | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
    read: Callable[[str], Spend] | None = None,
) -> None:
    """Отказ `ModelLimitReached`, если потолок расхода пространства достигнут.

    `tenant` не задан — берётся из контекста обращения; нет и там — проверки нет.
    `clock` и `read` — швы для теста.
    """
    код = tenant if tenant is not None else current_scope().tenant
    if not код or is_hq(код):
        return
    spend = _cached(canonical_tenant(код), clock=clock, read=read or month_spend)
    if spend is not None and spend.cap is not None and spend.level == LEVEL_OVER:
        logger.info("потолок расхода модели достигнут: %s %s из %s $", код, spend.spent, spend.cap)
        raise ModelLimitReached
