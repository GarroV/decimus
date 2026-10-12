"""Охват пиццерий на площадках — картах и агрегаторах (D424).

Вопрос экрана: на каких картах и агрегаторах есть каждая пиццерия и свежие ли
там данные. Строка — работающая пиццерия из реестра `agg.units`, колонка —
площадка, ячейка — одно из четырёх:

- **оценка** — точка привязана и оценка есть; `stale` — последняя оценка старше
  `STALE_DAYS`, новые не приходят (не авария: помечается значком, не строкой);
- **без оценки** — точка привязана, но оценок у неё ещё нет;
- **нет на площадке** — площадка в стране пиццерии работает, а привязанной точки
  нет (не нашлась или её ещё не привязали);
- **нет в стране** — площадки в этой стране нет, ячейка пустая.

Расчётов оценки здесь нет — берётся то, что собрано, в родной шкале площадки.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from src.db.agg_store import CoverageRow, UnitRow

STALE_DAYS = 7
NEW_DAYS = 30
MAPS_SCALE = 5

SCORE = "score"
UNRATED = "unrated"
MISSING = "missing"
ABSENT = "absent"

KIND_MAP = "map"
KIND_AGG = "agg"

#: Порядок колонок агрегаторов: сначала крупные, дальше по алфавиту — как в блоке на «Рейтингах».
ORDER = ("wolt", "glovo", "bolt_food", "yandex_eda", "yemeksepeti", "trendyol_go")


@dataclass(frozen=True)
class Platform:
    key: str
    kind: str


@dataclass(frozen=True)
class Cell:
    state: str
    score: float | None = None
    scale: int | None = None
    on_date: date | None = None
    stale: bool = False


@dataclass(frozen=True)
class Row:
    unit: UnitRow
    is_new: bool
    cells: Mapping[str, Cell]


@dataclass(frozen=True)
class Coverage:
    platforms: tuple[Platform, ...]
    rows: tuple[Row, ...]
    new: int  # новых пиццерий за `NEW_DAYS`
    unlinked: int  # пиццерий без точки хотя бы на одном ожидаемом агрегаторе


def is_stale(on_date: date | None, today: date) -> bool:
    """Данные старше недели: новые не приходят."""
    return on_date is not None and (today - on_date).days > STALE_DAYS


def is_new(unit: UnitRow, today: date) -> bool:
    """Пиццерия появилась в реестре за последние `NEW_DAYS`; «была с самого начала» — нет."""
    return unit.first_seen is not None and (today - unit.first_seen).days <= NEW_DAYS


def _scored(score: float, scale: int, on_date: date, today: date) -> Cell:
    return Cell(SCORE, score, scale, on_date, is_stale(on_date, today))


def _agg_cell(
    key: str,
    unit: UnitRow,
    linked: Mapping[tuple[str, str], CoverageRow],
    expected: Collection[str],
    today: date,
) -> Cell:
    row = linked.get((key, unit.dodo_id))
    if row is None:
        return Cell(MISSING if unit.country in expected else ABSENT)
    if row.score is None or row.scale is None or row.on_date is None:
        return Cell(UNRATED)
    return _scored(row.score, row.scale, row.on_date, today)


def _map_cell(latest: Mapping[str, tuple[float, date]], unit: UnitRow, today: date) -> Cell:
    found = latest.get(unit.dodo_id)
    if found is None:
        return Cell(MISSING)
    return _scored(found[0], MAPS_SCALE, found[1], today)


def _agg_order(keys: Iterable[str]) -> list[str]:
    return sorted(keys, key=lambda k: (k not in ORDER, ORDER.index(k) if k in ORDER else 0, k))


def build(
    units: Sequence[UnitRow],
    maps: Sequence[tuple[str, Mapping[str, tuple[float, date]]]],
    linked: Sequence[CoverageRow],
    agg_countries: Mapping[str, Collection[str]],
    today: date,
    *,
    country: str | None = None,
) -> Coverage:
    """Охват по работающим пиццериям (одной страны, если задана).

    `maps` — пары (ключ карты, оценка пиццерий на ней); `agg_countries` — страны,
    где агрегатор ожидается (его сборщик или его точки в справочнике). Колонка
    агрегатора есть, если он ожидается хотя бы в одной показанной стране."""
    shown = [u for u in units if u.working and (country is None or u.country == country)]
    by_point = {(r.aggregator, r.dodo_id): r for r in linked}
    shown_countries = {u.country for u in shown}
    aggs = _agg_order(k for k, cs in agg_countries.items() if shown_countries & set(cs))
    platforms = tuple(Platform(k, KIND_MAP) for k, _ in maps) + tuple(
        Platform(k, KIND_AGG) for k in aggs
    )
    rows = []
    for unit in shown:
        cells = {k: _map_cell(latest, unit, today) for k, latest in maps}
        cells.update({k: _agg_cell(k, unit, by_point, agg_countries[k], today) for k in aggs})
        rows.append(Row(unit, is_new(unit, today), cells))
    return Coverage(
        platforms,
        tuple(rows),
        sum(1 for r in rows if r.is_new),
        sum(1 for r in rows if any(r.cells[k].state == MISSING for k in aggs)),
    )
