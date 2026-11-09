"""Карта за месяц по оценкам, поставленным в этом месяце (D732, D733, docs/21-quality.md).

Ошибка здесь молчаливая: неверная средняя выглядит правдоподобно, поэтому правила под тестами
(`tests/test_maps_month.py`). Чистые функции: база и Pointer сюда не заходят.

**Правила.**

- Сырое значение карты за месяц — среднее арифметическое оценок, поставленных в этом месяце
  (по дате публикации), без удалённых. Вес — число этих оценок.
- Месяц не принимается, если оценок 0 или их меньше 10% от среднего числа оценок за три
  предыдущих месяца (`THRESHOLD_SHARE`). Тогда берётся итоговое значение карты за предыдущий
  месяц — рекурсивно, в пределах загруженной истории (`floor`) — вместе с его весом и пометкой
  «перенесено из <месяц>». Истории нет — у карты нет значения.
- Правило применяется к каждой карте отдельно. Среднее за три месяца считается по сырым
  числам оценок, а не по перенесённым значениям, и только по месяцам внутри истории.
- Значение пиццерии по всем картам — взвешенное числом оценок среднее значений карт:
  `domain.quality.maps_score`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

#: Месяц принимается, если оценок не меньше этой доли от среднего за три предыдущих месяца (D733).
THRESHOLD_SHARE = Decimal("0.1")
PRIOR_MONTHS = 3


@dataclass(frozen=True)
class MonthStat:
    """Оценки карты за месяц: сколько их и сумма звёзд."""

    count: int
    total: Decimal


@dataclass(frozen=True)
class MonthValue:
    """Значение карты за месяц: оценка, вес и откуда взято (`None` — из этого же месяца)."""

    score: Decimal
    count: int
    carried_from: date | None


def shift_month(month: date, delta: int) -> date:
    """Первое число месяца, сдвинутого на `delta` месяцев."""
    index = month.year * 12 + month.month - 1 + delta
    return date(index // 12, index % 12 + 1, 1)


def _accepted(stats: Mapping[date, MonthStat], month: date, floor: date) -> bool:
    count = stats[month].count if month in stats else 0
    if count <= 0:
        return False
    prior = [shift_month(month, -i) for i in range(1, PRIOR_MONTHS + 1)]
    inside = [m for m in prior if m >= floor]
    if not inside:
        return True
    mean_times_n = sum(stats[m].count for m in inside if m in stats)
    # count >= share * (mean_times_n / len(inside)) без деления
    return Decimal(count) * len(inside) >= THRESHOLD_SHARE * mean_times_n


def month_value(stats: Mapping[date, MonthStat], month: date, *, floor: date) -> MonthValue | None:
    """Итоговое значение карты за месяц по правилам модуля; `None` — значения нет.

    `stats` — оценки по первым числам месяцев, `floor` — первый месяц загруженной истории."""
    carried: date | None = None
    current = month
    while current >= floor:
        if _accepted(stats, current, floor):
            stat = stats[current]
            return MonthValue(stat.total / stat.count, stat.count, carried)
        current = shift_month(current, -1)
        carried = current
    return None
