"""Расчёты страницы «Качество» (docs/21-quality.md): средние КР, карт и агрегаторов, доли заказов,
веса и итоговый рейтинг по методике аналитика (D719).

Мест на странице нет (D677), итоговый рейтинг и веса есть (D719). Ошибка здесь молчаливая —
неверное среднее выглядит правдоподобно, поэтому всё под тестами. Единица расчёта — пиццерия за
месяц; страна — простое среднее своих пиццерий, а доли и суммы страны — по суммам их заказов и
выручки.

Оценку проверки здесь не считают: её приносит движок (`engine/audit.py score`), процент
приходит готовым. Числа — `Decimal`: деньги и средние не должны плыть на двоичной дроби.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)
ONE = Decimal(1)
FIVE = Decimal(5)

#: РКО — сто баллов, в пять баллов делением на двадцать.
RKO_DIVISOR = Decimal(20)
#: Вес карт — экспертное решение (D563).
MAPS_WEIGHT = Decimal("0.2")
#: Пороги веса РКО по проверкам РКО в неделю: (от, вес); ноль проверок — вес ноль.
RKO_TIERS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal(5), Decimal("0.5")),
    (Decimal(2), Decimal("0.3")),
    (ZERO, Decimal("0.1")),
)


@dataclass(frozen=True)
class Orders:
    """Заказы пиццерии за месяц по группам: агрегаторы, приложение и сайт, прочее."""

    aggregators: int
    app_site: int
    other: int

    @property
    def total(self) -> int:
        return self.aggregators + self.app_site + self.other


def mean(values: Sequence[Decimal]) -> Decimal | None:
    """Простое среднее; пусто — `None`, а не ноль."""
    return sum(values, ZERO) / len(values) if values else None


def five_point(score: Decimal, scale: int) -> Decimal:
    """Оценка площадки в пятибалльной шкале: оценка × 5 / максимум шкалы."""
    return score * FIVE / Decimal(scale)


def share(part: int | Decimal, total: int | Decimal) -> Decimal | None:
    """Доля от целого, 0–1; целого нет — `None`."""
    return Decimal(part) / Decimal(total) if total else None


def combine_kr(
    dine_avg: Decimal | None, dine_count: int, delivery_avg: Decimal | None, delivery_count: int
) -> Decimal | None:
    """КР из средних зала и доставки — среднее, взвешенное числом оценок."""
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
    """Карты: `(оценка, число оценок)` по картам (Google и Яндекс; 2ГИС и прочие не берём).

    Среднее, взвешенное числом оценок; карта без оценок в среднем не участвует, у всех ноль —
    оценки карт нет."""
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
class Overall:
    """Итоговый рейтинг пиццерии за месяц, из пяти; `rko5` — РКО, приведённый к пяти."""

    score: Decimal | None
    rko5: Decimal | None
    #: Веса, вошедшие в итог: у компонента без оценки — ноль.
    weights: Weights

    @property
    def incomplete(self) -> bool:
        """Сумма весов меньше 100%: итог нормирован на неё (D719), помечается «неполный»."""
        return self.score is not None and self.weights.total < ONE


def rko_weight(checks_per_week: Decimal | None) -> Decimal:
    """Вес РКО: 0 проверок → 0; < 2 → 10%; < 5 → 30%; ≥ 5 → 50%."""
    if checks_per_week is None or checks_per_week <= ZERO:
        return ZERO
    return next(w for floor, w in RKO_TIERS if checks_per_week >= floor)


def overall(
    *,
    rko: Decimal | None,
    rko_checks_per_week: Decimal | None,
    kr: Decimal | None,
    maps: Decimal | None,
    aggregators: Decimal | None,
    orders: Orders,
) -> Overall:
    """Итог по методике аналитика: Σ вес × оценка; `rko` — сто баллов, остальное — пять.

    Остаток 1 − вес РКО − вес карт делится между КР и агрегаторами по их долям в заказах
    «приложение и сайт + агрегаторы» (прочие каналы не участвуют). Компонент без оценки
    получает вес ноль; если сумма весов вышла меньше 100%, итог делится на неё (п. 10
    инструкции, D719) — иначе он занижался бы на выпавший вес."""
    rko5 = None if rko is None else rko / RKO_DIVISOR
    w_rko = rko_weight(rko_checks_per_week)
    rest = ONE - w_rko - MAPS_WEIGHT
    digital = orders.aggregators + orders.app_site
    weights = Weights(
        rko=w_rko if rko5 is not None else ZERO,
        kr=rest * orders.app_site / digital if digital and kr else ZERO,
        maps=MAPS_WEIGHT if maps is not None else ZERO,
        aggregators=(
            rest * orders.aggregators / digital if digital and aggregators is not None else ZERO
        ),
    )
    parts = (
        (weights.rko, rko5),
        (weights.kr, kr),
        (weights.maps, maps),
        (weights.aggregators, aggregators),
    )
    total = weights.total
    if not total:
        return Overall(None, rko5, weights)
    score = sum((w * s for w, s in parts if s is not None and w), ZERO) / total
    return Overall(score, rko5, weights)
