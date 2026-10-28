"""Расчёты страницы «Качество» (docs/21-quality.md): среднее КР, карт и агрегаторов, доли заказов.

Страница — рабочая страница здоровья, а не рейтинг: сводной оценки и мест нет (D677). Здесь
остались только числа, которые она показывает, и ошибка в них молчаливая — неверное среднее
выглядит правдоподобно, поэтому они под тестами. Единица расчёта — пиццерия за месяц; страна —
простое среднее своих пиццерий, а доли и суммы страны — по суммам их заказов и выручки.

Оценку проверки здесь не считают: её приносит движок (`engine/audit.py score`), процент
приходит готовым. Числа — `Decimal`: деньги и средние не должны плыть на двоичной дроби.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)
FIVE = Decimal(5)


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
