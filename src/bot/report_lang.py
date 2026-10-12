"""Язык отчёта в конце проверки (D415): какие языки предложить этой пиццерии.

Перечень зависит от страны пиццерии и лежит в данных (`domain.report_langs`).
Страна проверки — из справочника точек пространства (по названию точки), а
если точки в справочнике нет или база недоступна — по городу проверки
(`geo.CITY_COUNTRY`). Ни того ни другого — перечень по умолчанию: не пустить
человека к отчёту из-за пробела в справочнике хуже, чем показать ему два языка.
"""

from __future__ import annotations

import asyncio
import logging

from src import domain
from src.db import directory
from src.db.errors import DbError
from src.db.reach import reach_of
from src.domain import report_langs

logger = logging.getLogger(__name__)


def _unit_country(unit: str, tenant: str) -> str | None:
    """Страна точки по названию или синониму; `None` — точки нет или базы нет."""
    wanted = unit.strip().casefold()
    if not wanted:
        return None
    try:
        units = directory.list_units(reach=reach_of(tenant))
    except DbError as exc:
        logger.warning("справочник точек недоступен, страну отчёта берём по городу: %s", exc)
        return None
    for one in units:
        names = (one.name, *one.aliases)
        if one.country and wanted in {name.strip().casefold() for name in names}:
            return one.country
    return None


def inspection_country(inspection: domain.Inspection) -> str | None:
    """Страна проверки: точка справочника, затем город, затем неизвестна."""
    return _unit_country(inspection.unit, inspection.tenant) or report_langs.country_of_city(
        inspection.city
    )


def langs_for_inspection(inspection: domain.Inspection) -> list[str]:
    """Языки отчёта для этой проверки. Синхронно: справочник и файл читаются с диска и из базы."""
    return report_langs.report_langs_for(inspection_country(inspection))


async def offered_langs(inspection: domain.Inspection) -> list[str]:
    """То же в потоке — чтобы поход в базу не останавливал бот для остальных (T101)."""
    return await asyncio.to_thread(langs_for_inspection, inspection)
