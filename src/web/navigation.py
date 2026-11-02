"""Постоянное подменю оболочки: доступные разделы рейтингов без запроса данных.

В самом разделе экран подставляет ссылки с выбранным срезом и периодом;
на остальных страницах остаются обычные входы, без ложных точек свежести.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from src.domain.permissions import role_may
from src.domain.tenants import HQ_TENANT

from . import ratings_nav
from .texts import t


def ratings_menu(account: Any, lang: str, prefix: str) -> tuple[ratings_nav.Item, ...]:
    """Состав меню следует тем же правам, что и маршруты рейтингов."""
    if account is None:
        return ()
    inspections = role_may(account.role, account.tenant, "view.registry")
    return tuple(
        ratings_nav.Item(
            key=key,
            title=t(f"ratings.sec.{key}", lang),
            href=f"{prefix}/ratings/{key}?{urlencode({'lang': lang})}",
            current=False,
            dot=None,
            dot_word="",
        )
        for key in ratings_nav.visible(account.tenant == HQ_TENANT, inspections=inspections)
    )
