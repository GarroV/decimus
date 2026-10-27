"""Плитка «Стабильно ниже порога» (D658): собирает источники и отдаёт общий список.

Правила — в `src.ratings.risk_sources`; здесь только чтение источников в срезе
экрана и охвате вошедшего. Источник, который не прочитался, не роняет плитку:
остальные показаны, а плитка прямо говорит, чего не хватает (не «никого» вместо
«не знаем»).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.db import agg_store, unit_scores
from src.db.errors import DbError, RatingsError
from src.db.reach import Reach
from src.ratings import risk_sources as rsrc
from src.ratings.links import hex_id
from src.ratings.model import RKO, RS
from src.ratings.summary import RiskUnit

from .texts import t

logger = logging.getLogger(__name__)

#: Источники, которые могут не прочитаться: площадки доставки и наши проверки.
UNREAD_AGGREGATORS = "aggregators"
UNREAD_INSPECTIONS = rsrc.INSPECTIONS


@dataclass(frozen=True)
class CombinedRisk:
    rows: tuple[rsrc.RiskRow, ...]
    unread: tuple[str, ...]


def source_names(agg_names: dict[str, str], lang: str) -> dict[str, str]:
    """Название источника словами: площадки — как в блоке агрегаторов, остальное — из текстов."""
    return {
        **agg_names,
        RS: t("ratings.rs", lang),
        RKO: t("ratings.rko", lang),
        rsrc.INSPECTIONS: t("ratings.risk.src.inspections", lang),
    }


def _unit(code: str) -> str:
    return hex_id(code) or code


def build(
    zone: Sequence[RiskUnit],
    *,
    countries: Sequence[str],
    until: date,
    reach: Reach,
    inspection_threshold: float,
) -> CombinedRisk:
    unread: list[str] = []
    points: tuple[rsrc.PointScores, ...] = ()
    inspections: tuple[rsrc.InspectionScores, ...] = ()
    try:
        points = tuple(
            rsrc.PointScores(
                h.aggregator,
                _unit(h.dodo_id),
                h.dodo_name or h.dodo_id,
                h.country_code,
                h.scale,
                h.scores,
            )
            for h in agg_store.recent(countries, until=until, n=rsrc.AGG_WINDOW)
        )
    except RatingsError:
        logger.warning("История оценок агрегаторов для зоны риска не прочиталась", exc_info=True)
        unread.append(UNREAD_AGGREGATORS)
    try:
        inspections = tuple(
            rsrc.InspectionScores(_unit(u.code), u.name, u.country, u.pcts)
            for u in unit_scores.recent_pcts(
                reach=reach, countries=countries, until=until, n=rsrc.INSPECTION_WINDOW
            )
        )
    except DbError:
        logger.warning("Оценки проверок для зоны риска не прочитались", exc_info=True)
        unread.append(UNREAD_INSPECTIONS)
    rows = rsrc.combine(zone, points, inspections, inspection_threshold=inspection_threshold)
    return CombinedRisk(rows, tuple(unread))
