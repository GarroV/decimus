"""Запрос плана по счётчикам движка: любое нарушение D1/D2/D3, независимо от оценки."""

from collections.abc import Mapping
from typing import Any

# Решение владельца о рабочем процессе, а не ставки или пороги оценки.
TRIGGER_LEVELS = ("D1", "D2", "D3")


def needs_action_plan(counts: Mapping[str, Any]) -> bool:
    """D0, рекомендации и информационные записи сами по себе не требуют плана."""
    for level in TRIGGER_LEVELS:
        raw = counts.get(level, 0)
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Счётчик {level} у проверки не число ({raw!r}) — нужен ли экшн-план, "
                f"не понять. Счётчики кладёт движок; такой ответ — поломка, а не ноль"
            ) from exc
        if number > 0:
            return True
    return False
