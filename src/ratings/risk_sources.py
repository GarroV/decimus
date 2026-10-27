"""Плитка «Стабильно ниже порога» по любому источнику (D658): РС, РКО, агрегаторы, наши проверки.

Чистые правила, без базы: что считать «стабильно ниже» у каждого источника и как
склеить источники в один список пиццерий. Оценки приходят готовыми — из зоны риска
РС и РКО (`summary.risk_zone`), из снимков агрегаторов и из процента проверки, который
записал движок; здесь ничего не пересчитывается (CLAUDE.md, «Оценку не считать заново»).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .model import RKO, RS
from .summary import RiskUnit, shown

#: D658. Сколько последних недельных снимков агрегатора должно быть ниже порога площадки.
AGG_WINDOW = 4
#: D658. Сколько последних принятых проверок (не исторических) должно быть ниже `risk_threshold`.
INSPECTION_WINDOW = 2
#: D658. Порог площадки в её родной шкале: Wolt — 9,0 из 10, Glovo — 90 %.
AGG_THRESHOLDS: dict[str, float] = {"wolt": 9.0, "glovo": 90.0}
#: D658. Остальные площадки — ниже этой доли максимума их шкалы (из 5: 4,5).
AGG_OTHER_SHARE = 0.9
#: Код источника «наши проверки» рядом с кодами РС, РКО и агрегаторов.
INSPECTIONS = "inspections"

_COARSE_SCALE = 10  # шкалы 10 и 100 показываются с одним знаком, из 5 — с двумя (как на плитке)


@dataclass(frozen=True)
class PointScores:
    """Снимки одной точки агрегатора, привязанной к пиццерии; новые первыми."""

    aggregator: str
    unit: str
    unit_name: str
    country: str
    scale: int
    scores: tuple[float, ...]


@dataclass(frozen=True)
class InspectionScores:
    """Проценты принятых проверок пиццерии, записанные движком; новые первыми."""

    unit: str
    unit_name: str
    country: str
    pcts: tuple[float, ...]


@dataclass(frozen=True)
class Source:
    """Источник, у которого пиццерия стабильно ниже порога; `scores` — старые первыми."""

    code: str
    scores: tuple[float, ...]


@dataclass(frozen=True)
class RiskRow:
    unit: str
    unit_name: str
    country: str
    sources: tuple[Source, ...]


def agg_threshold(aggregator: str, scale: int) -> float:
    """Порог площадки: названный в решении или доля шкалы у остальных."""
    return AGG_THRESHOLDS.get(aggregator, scale * AGG_OTHER_SHARE)


def _aggregator_flag(point: PointScores) -> Source | None:
    window = point.scores[:AGG_WINDOW]
    if len(window) < AGG_WINDOW:
        return None
    digits = 1 if point.scale >= _COARSE_SCALE else 2
    limit = agg_threshold(point.aggregator, point.scale)
    if all(round(s, digits) < limit for s in window):
        return Source(point.aggregator, tuple(reversed(window)))
    return None


def _inspection_flag(row: InspectionScores, threshold: float) -> Source | None:
    window = row.pcts[:INSPECTION_WINDOW]
    if len(window) < INSPECTION_WINDOW or not all(shown(p) < threshold for p in window):
        return None
    return Source(INSPECTIONS, tuple(reversed(window)))


def combine(
    zone: Sequence[RiskUnit],
    points: Sequence[PointScores],
    inspections: Sequence[InspectionScores],
    *,
    inspection_threshold: float,
) -> tuple[RiskRow, ...]:
    """Пиццерии, стабильно низкие хотя бы по одному источнику; чем больше источников — тем выше,
    дальше по имени. Источник пиццерии — один раз: две точки одной площадки дают один флаг."""
    found: dict[str, tuple[str, str, list[Source]]] = {}

    def add(unit: str, name: str, country: str, source: Source | None) -> None:
        if source is None:
            return
        _, _, sources = found.setdefault(unit, (name, country, []))
        if all(s.code != source.code for s in sources):
            sources.append(source)

    for z in zone:
        add(z.unit, z.unit_name, z.country, Source(z.rating_type, z.scores))
    # Имя — первое найденное: РС и РКО (рейтинг), проверки (справочник), площадки (витрина).
    for i in inspections:
        add(i.unit, i.unit_name, i.country, _inspection_flag(i, inspection_threshold))
    for p in points:
        add(p.unit, p.unit_name, p.country, _aggregator_flag(p))
    order = {RS: 0, RKO: 1, INSPECTIONS: 9}
    rows = [
        RiskRow(unit, name, country, tuple(sorted(sources, key=lambda s: order.get(s.code, 5))))
        for unit, (name, country, sources) in found.items()
    ]
    return tuple(sorted(rows, key=lambda r: (-len(r.sources), r.unit_name.casefold(), r.unit)))
