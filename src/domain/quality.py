"""Расчёт «Качества»: ЛКО и ЭС — ядро (D561–D566; docs/21-quality.md).

Ошибка здесь молчаливая: неверный вес даёт правдоподобное число, а не сбой. Формулы —
методика аналитика, пересказ в `docs/21-quality.md`; менять их можно только вместе с
аналитиком, а не «по улучшению» (D564). Единица расчёта — пиццерия × месяц; страна —
простое среднее своих пиццерий-месяцев.

**ЛКО** (лучший клиентский опыт), пятибалльная шкала, четыре компонента:

- РКО: оценка / 20; вес зависит от среднего числа проверок РКО в неделю;
- КР (приложение и сайт); карты — среднее Google и Яндекса по числу оценок, вес
  фиксированный; агрегаторы — среднее оценок площадок в пятибалльной шкале с весом их
  заказов;
- остаток веса `1 − вес РКО − вес карт` делится между КР и агрегаторами пропорционально
  их долям в заказах. Прочие каналы (колл-центр, касса, киоск) в делении не участвуют.

Итог — сумма «вес × оценка» **без пересчёта на сумму весов**: недостающий компонент
весит ноль, и если сумма весов меньше 100%, это только пометка для экрана.

**ЭС** (эталон стандартов) = доля аудита × проверка decimus + (1 − доля) × РС. Нет проверки
в месяце — ЭС нет, вес на РС не переносится.

Оценку проверки здесь не считают: её приносит движок (`engine/audit.py score`), сюда
процент приходит готовым. Числа — `Decimal`: деньги и веса не должны плыть на двоичной дроби.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)
ONE = Decimal(1)

#: РКО — сто баллов, приводится к пяти делением на двадцать.
RKO_DIVISOR = Decimal(20)
#: Вес карт — экспертное решение (D563), настройка по умолчанию.
MAPS_WEIGHT = Decimal("0.2")
#: В формуле агрегаторов вес карт вписан числом (так в таблице аналитика) и от настройки
#: «вес карт» не зависит; пока настройка равна умолчанию, расхождения нет.
AGGREGATOR_MAPS_WEIGHT = Decimal("0.2")
#: Доля проверки decimus в ЭС по умолчанию (настройка).
AUDIT_SHARE = Decimal("0.5")
FIVE = Decimal(5)

#: Пороги веса РКО по числу проверок в неделю: (от, вес); ниже первого порога — ноль.
_RKO_TIERS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal(5), Decimal("0.5")),
    (Decimal(2), Decimal("0.3")),
    (ZERO, Decimal("0.1")),
)


@dataclass(frozen=True)
class Orders:
    """Заказы пиццерии за месяц по группам: агрегаторы (N), приложение и сайт (O), прочее (P)."""

    aggregators: int
    app_site: int
    other: int

    @property
    def total(self) -> int:
        return self.aggregators + self.app_site + self.other


@dataclass(frozen=True)
class Weights:
    rko: Decimal
    kr: Decimal
    maps: Decimal
    aggregators: Decimal

    @property
    def total(self) -> Decimal:
        return self.rko + self.kr + self.maps + self.aggregators


@dataclass(frozen=True)
class Scores:
    """Пятибалльные оценки компонентов; `None` — данных нет."""

    rko: Decimal | None
    kr: Decimal | None
    maps: Decimal | None
    aggregators: Decimal | None


@dataclass(frozen=True)
class Lko:
    score: Decimal | None
    scores: Scores
    #: Веса, вошедшие в итог: у компонента без оценки — ноль.
    weights: Weights
    weight_sum: Decimal

    @property
    def sum_below_full(self) -> bool:
        """Сумма весов меньше 100%: часть веса выпала, итог занижен (пометка, не пересчёт)."""
        return self.weight_sum < ONE


@dataclass(frozen=True)
class Es:
    score: Decimal | None
    audit: Decimal | None
    rs: Decimal | None
    #: `ok`, `no_audit` (нет проверки в месяце), `no_rs` (нет РС).
    status: str


def mean(values: Sequence[Decimal]) -> Decimal | None:
    """Простое среднее; пусто — `None`, а не ноль."""
    return sum(values, ZERO) / len(values) if values else None


def five_point(score: Decimal, scale: int) -> Decimal:
    """Оценка площадки в пятибалльной шкале: оценка × 5 / максимум шкалы."""
    return score * FIVE / Decimal(scale)


def rko_weight(checks_per_week: Decimal | None) -> Decimal:
    """Вес РКО по среднему числу проверок в неделю: 0 → 0; < 2 → 10%; < 5 → 30%; ≥ 5 → 50%."""
    if checks_per_week is None or checks_per_week <= ZERO:
        return ZERO
    for floor, weight in _RKO_TIERS:
        if checks_per_week >= floor:
            return weight
    return ZERO  # недостижимо: нижний порог — ноль; для типов


def combine_kr(
    dine_avg: Decimal | None, dine_count: int, delivery_avg: Decimal | None, delivery_count: int
) -> Decimal | None:
    """КР из средних зала и доставки — среднее, взвешенное числом оценок (допущение, docs)."""
    parts = [
        (avg, n)
        for avg, n in ((dine_avg, dine_count), (delivery_avg, delivery_count))
        if avg is not None and n > 0
    ]
    count = sum(n for _, n in parts)
    if not count:
        return None
    return sum((avg * n for avg, n in parts), ZERO) / count


def maps_score(ratings: Sequence[tuple[Decimal, int]]) -> Decimal | None:
    """Карты: `(оценка, число оценок)` по картам (Google, Яндекс там, где он есть; 2ГИС нет).

    Среднее, взвешенное числом оценок (решение владельца 28.10.2026); карта без оценок в
    среднем не участвует, у всех ноль — оценки карт нет."""
    used = [(score, n) for score, n in ratings if n > 0]
    count = sum(n for _, n in used)
    if not count:
        return None
    return sum((score * n for score, n in used), ZERO) / count


def aggregator_score(lines: Sequence[tuple[Decimal | None, int]]) -> Decimal | None:
    """Оценка агрегаторов: `(оценка в пятибалльной шкале | None, заказы)` по площадкам.

    Среднее по заказам; площадка без оценки или без заказов в среднем не участвует."""
    used = [(score, n) for score, n in lines if score is not None and n > 0]
    orders = sum(n for _, n in used)
    if not orders:
        return None
    return sum((score * n for score, n in used), ZERO) / orders


def lko(
    *,
    rko: Decimal | None,
    rko_checks_per_week: Decimal | None,
    kr: Decimal | None,
    maps: Decimal | None,
    aggregators: Decimal | None,
    orders: Orders,
    maps_weight: Decimal = MAPS_WEIGHT,
) -> Lko:
    """ЛКО пиццерии за месяц. `rko` — сто баллов, остальное уже в пяти."""
    rko5 = None if rko is None else rko / RKO_DIVISOR
    w_rko = rko_weight(rko_checks_per_week)
    digital = orders.aggregators + orders.app_site
    if digital == 0:
        w_kr = ZERO
        w_agg = ZERO
    else:
        w_kr = ZERO if not kr else (ONE - w_rko - maps_weight) * orders.app_site / digital
        w_agg = (
            ZERO
            if aggregators is None
            else (ONE - w_rko - AGGREGATOR_MAPS_WEIGHT) * orders.aggregators / digital
        )
    weights = Weights(
        rko=w_rko if rko5 is not None else ZERO,
        kr=w_kr,
        maps=maps_weight if maps is not None else ZERO,
        aggregators=w_agg,
    )
    parts = (
        (weights.rko, rko5),
        (weights.kr, kr),
        (weights.maps, maps),
        (weights.aggregators, aggregators),
    )
    known = [(w, s) for w, s in parts if s is not None]
    score = sum((w * s for w, s in known), ZERO) if known else None
    return Lko(
        score=score,
        scores=Scores(rko5, kr, maps, aggregators),
        weights=weights,
        weight_sum=weights.total,
    )


def es(*, audit: Decimal | None, rs: Decimal | None, audit_share: Decimal = AUDIT_SHARE) -> Es:
    """ЭС пиццерии за месяц; без проверки или без РС — не считается, вес не переносится."""
    if audit is None:
        return Es(None, None, rs, "no_audit")
    if rs is None:
        return Es(None, audit, None, "no_rs")
    return Es(audit_share * audit + (ONE - audit_share) * rs, audit, rs, "ok")


def places(values: Mapping[str, Decimal | None]) -> dict[str, int]:
    """Места по убыванию значения; равные — одно место, следующее без пропуска.

    Без значения места нет."""
    ranked = sorted({v for v in values.values() if v is not None}, reverse=True)
    rank = {v: i + 1 for i, v in enumerate(ranked)}
    return {k: rank[v] for k, v in values.items() if v is not None}
