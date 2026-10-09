"""Пространства партнёров на экране «Пользователи» (#585, D364).

Дверь веба в `src/db/spaces.py` для одного вопроса: «какие пространства есть,
с какими странами, и завести новое». Кому можно — решает правило охвата
(`access_policy.manages_spaces`), а сверяет маршрут.
"""

from __future__ import annotations

from src.db.spaces import SpaceRow, add_countries, create_partner_space, overview

__all__ = ["SpaceRow", "add_countries", "create_partner_space", "overview", "parse_countries"]


def parse_countries(text: str) -> tuple[str, ...]:
    """Страны из поля формы: через пробел или запятую, «ge, am» → ("GE", "AM")."""
    return tuple(часть.upper() for часть in text.replace(",", " ").split() if часть)
