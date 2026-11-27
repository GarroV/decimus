"""Ссылки на экран пиццерии и страны из «Качества» и «Рейтингов» (#1603).

Экраны статистики знают пиццерию по коду Dodo (`units.code`, 32 hex), а экран пиццерии
адресуется идентификатором справочника (`units.id`): здесь они сводятся. Ссылка есть
только там, где читатель откроет цель: справочник читается в охвате вошедшего (партнёр —
свои страны), а экран страны закрыт матрицей (`view.country`). Нет права или справочник не
прочитался — ссылки нет, имя остаётся текстом, а не ссылкой в 403.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from flask import url_for

from src.db import directory
from src.db.errors import DbError

from . import auth, guard

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnitTarget:
    unit_id: str
    country: str


def by_code() -> Mapping[str, UnitTarget]:
    """Код Dodo → (идентификатор справочника, страна) пиццерий в охвате вошедшего.

    Без права на экран страны или при сбое чтения — пусто (ссылок нет)."""
    if not guard.may("view.country"):
        return {}
    try:
        units = directory.list_units(reach=auth.current_reach())
    except DbError:
        logger.warning("Справочник пиццерий для ссылок не прочитался", exc_info=True)
        return {}
    return {u.code: UnitTarget(u.id, u.country) for u in units if u.code and u.country}


def unit_href(target: UnitTarget | None, *, lang: str = "", inspection: str = "") -> str:
    """Экран пиццерии в «Странах» (D508, D539); с `inspection` — сразу с панелью проверки."""
    if target is None:
        return ""
    params: dict[str, Any] = {"unit": target.unit_id}
    if inspection:
        params["inspection"] = inspection
    if lang:
        params["lang"] = lang
    return url_for("country", code=target.country, **params) + f"#unit-{target.unit_id}"


def country_href(code: str, *, lang: str = "") -> str:
    """Экран страны; пусто, если читателю он закрыт."""
    if not guard.may("view.country") or not code:
        return ""
    extra: dict[str, Any] = {"lang": lang} if lang else {}
    return url_for("country", code=code, **extra)
