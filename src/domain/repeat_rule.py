"""Правило «пункт уже был нарушением в прошлой проверке» (D191, D255).

Общее для бота (`src/bot/repeats.py`) и загрузки через MCP: mcp бот не
импортирует, поэтому правило живёт в domain. Здесь только вопрос «спрашивать ли
о повторе»; решение «это повтор» остаётся за человеком.
"""

from __future__ import annotations

from collections.abc import Collection

#: Классы, у которых нет ставки за запись, — удваивать нечего (D191): `D3`
#: сжигает долю зоны целиком, `D0` — информационная запись без вычета, `R` —
#: рекомендация (D201).
NOTHING_TO_DOUBLE = frozenset({"D0", "D3", "R"})


def was_violation(previous_codes: Collection[str], *, code: str, level: str) -> bool:
    """Был ли этот пункт нарушением в прошлой проверке и уместен ли о нём вопрос."""
    return level not in NOTHING_TO_DOUBLE and code in previous_codes
