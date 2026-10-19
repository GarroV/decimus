"""Строки пиццерий экрана «Страны» (D467): одна строка на пиццерию.

Сводит в одну строку то, что раньше жило в двух блоках («Результаты проверок
по пиццериям» и «Свод пиццерий»): точку справочника, строку свода (партнёр,
адрес, открытие, статус), последнюю проверку за период, РС / РКО и оценки на
картах. Связь — КОДОМ Dodo (`Unit.code` ↔ `Profile.dodo_id`), а не названием;
строка свода, которой нет в справочнике, остаётся отдельной строкой — без
проверок и оценок, но с её сведениями.

Ничего не считает: оценки и буквы приходят готовыми. Чтение базы — только в
`load_*`, и сбой чтения гасит свой столбец, а не экран страны.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.db import directory, maps_store, queries, unit_profiles
from src.db.errors import DbError
from src.db.models import InspectionRow
from src.db.reach import Reach
from src.ratings.maps import SHOWN_PROVIDERS
from src.ratings.svod import normalize as svod_normalize

from . import home_ratings
from .overview import PointRow

log = logging.getLogger(__name__)

#: Ключ строки, которой нет в справочнике (есть только в своде): `svod:` + имя.
SVOD_KEY = "svod:"

#: Сколько проверок пиццерии показывает экран: последние, а не вся история.
HISTORY_LIMIT = 30

#: Порядок стадий свода в таблице; стадия `closed` уходит в свёрнутый блок.
_STAGE_ORDER = {"open": 0, "paused": 1, "pipeline": 2}


@dataclass(frozen=True)
class UnitRow:
    """Пиццерия страны одной строкой таблицы и панели."""

    #: Ключ для адреса панели: идентификатор справочника или `svod:<имя>`.
    key: str
    name: str
    #: Идентификатор справочника; пусто — точки в справочнике нет (карточки нет).
    unit_id: str
    stage: str
    city: str = ""
    partner: str = ""
    address: str = ""
    opened: date | None = None
    closed_on: date | None = None
    status: str = ""
    #: Другие написания названия (синонимы справочника, D538) — для карточки страны.
    aliases: tuple[str, ...] = ()
    restaurant_on: date | None = None
    delivery_on: date | None = None
    #: Площадь, м², и посадочные места из свода; `None` — в своде нет.
    area: float | None = None
    seats: int | None = None
    #: Почта партнёра из свода: показывается только УК (D375).
    partner_email: str = ""
    #: Последняя проверка ЗА ПЕРИОД экрана; `None` — за период не проверяли.
    last: PointRow | None = None
    #: Дата последней проверки ВООБЩЕ, не за период; `None` — не проверяли ни разу.
    last_ever: date | None = None
    rs: float | None = None
    rko: float | None = None
    #: Оценки на картах: код карты → средняя.
    maps: Mapping[int, float] = field(default_factory=dict)

    @property
    def is_closed(self) -> bool:
        return self.stage == "closed"


@dataclass(frozen=True)
class UnitsData:
    """Всё, что нужно таблице: строки и что из этого не прочиталось."""

    rows: tuple[UnitRow, ...] = ()
    #: Свод пиццерий не прочитался — таблица остаётся по справочнику и проверкам.
    profiles_failed: bool = False
    #: РС / РКО не прочитались — столбцы пустые, и экран говорит об этом.
    ratings_failed: bool = False
    maps_failed: bool = False
    #: Есть ли у хоть одной строки РС / РКО и карты: пустой столбец не рисуется.
    has_ratings: bool = False
    has_maps: bool = False

    @property
    def open_rows(self) -> tuple[UnitRow, ...]:
        return tuple(r for r in self.rows if not r.is_closed)

    @property
    def closed_rows(self) -> tuple[UnitRow, ...]:
        return tuple(r for r in self.rows if r.is_closed)

    def find(self, key: str) -> UnitRow | None:
        return next((r for r in self.rows if r.key == key), None)


def _sort_key(row: UnitRow) -> tuple[int, float, str]:
    """Проверенные сверху, худшие первыми; остальные — по стадии и имени."""
    if row.last is not None:
        return (0, row.last.pct, row.name)
    return (1 + _STAGE_ORDER.get(row.stage, 0), 0.0, row.name)


def _from_profile(profile: unit_profiles.Profile) -> dict[str, Any]:
    """Поля строки из свода пиццерий — одним местом для точки справочника и для строки свода."""
    return {
        "stage": profile.stage,
        "city": profile.city or "",
        "partner": profile.partner or "",
        "address": profile.address or "",
        "opened": profile.restaurant_on or profile.delivery_on,
        "closed_on": profile.closed_on,
        "status": profile.status,
        "restaurant_on": profile.restaurant_on,
        "delivery_on": profile.delivery_on,
        "area": float(profile.total_area) if profile.total_area is not None else None,
        "seats": profile.seats,
        "partner_email": profile.partner_email or "",
    }


def build_rows(
    units: Sequence[directory.Unit],
    profiles: Sequence[unit_profiles.Profile],
    points: Mapping[str, PointRow],
    ratings: Mapping[str, tuple[float | None, float | None]],
    maps: Mapping[str, Mapping[int, float]],
    last_ever: Mapping[str, date] | None = None,
) -> tuple[UnitRow, ...]:
    """Свести справочник, свод, проверки периода и оценки в строки."""
    last_ever = last_ever or {}
    by_code = {p.dodo_id: p for p in profiles if p.dodo_id}
    # Точка без кода Dodo (заведённая с экрана «Страны», D536, без кода) связывается со
    # строкой справочника названием — только если по коду пары не нашлось.
    by_name = {p.name_normalized: p for p in profiles if p.name_normalized}
    used: set[int] = set()
    rows: list[UnitRow] = []
    for unit in units:
        profile = by_code.get(unit.code or "")
        if profile is None and not unit.code:
            profile = by_name.get(svod_normalize(unit.name))
            if profile is not None and id(profile) in used:
                profile = None
        if profile is not None:
            used.add(id(profile))
        rs, rko = ratings.get(unit.code or "", (None, None))
        сведения = _from_profile(profile) if profile else {"stage": "open"}
        rows.append(
            UnitRow(
                key=unit.id,
                name=unit.name,
                unit_id=unit.id,
                **{**сведения, "city": сведения.get("city") or unit.city or ""},
                aliases=tuple(a for a in unit.aliases if a != unit.name),
                last=points.get(unit.name),
                last_ever=last_ever.get(unit.name),
                rs=rs,
                rko=rko,
                maps=maps.get(unit.code or "", {}),
            )
        )
    for profile in profiles:
        if id(profile) in used:
            continue
        rows.append(
            UnitRow(
                key=SVOD_KEY + (profile.name_normalized or profile.name),
                name=profile.name,
                unit_id="",
                **_from_profile(profile),
            )
        )
    return tuple(sorted(rows, key=_sort_key))


def _profiles(code: str) -> tuple[tuple[unit_profiles.Profile, ...], bool]:
    try:
        return unit_profiles.by_country(code), False
    except DbError:
        log.warning("Сведения о пиццериях страны не прочитались", exc_info=True)
        return (), True


def _ratings(code: str, until: date) -> tuple[dict[str, tuple[float | None, float | None]], bool]:
    try:
        return home_ratings.load_latest((code,), until=until), False
    except DbError:
        log.warning("Оценки рейтинга по пиццериям страны не прочитались", exc_info=True)
        return {}, True


def _maps(until: date) -> tuple[dict[str, dict[int, float]], bool]:
    """Оценки пиццерий на картах: код Dodo → {карта: средняя}. Только показываемые карты."""
    out: dict[str, dict[int, float]] = {}
    try:
        for provider in SHOWN_PROVIDERS:
            for code, (avg, _count) in maps_store.unit_scores(provider, until=until).items():
                out.setdefault(code, {})[provider] = avg
    except DbError:
        log.warning("Оценки пиццерий на картах не прочитались", exc_info=True)
        return {}, True
    return out, False


def _last_ever(reach: Reach) -> dict[str, date]:
    """Дата последней проверки каждой точки за всё время, по названию точки.

    Тот же запрос, что у «Где нужно проверить» (`queries.unit_last_inspections`),
    без периода: новой выборки в `src/db` нет. Не прочиталось — пусто, и колонка
    показывает только проверки периода.
    """
    try:
        rows = queries.unit_last_inspections(reach=reach)
    except DbError:
        log.warning("Даты последних проверок точек не прочитались", exc_info=True)
        return {}
    return {name: last for name, _code, last, _n in rows if last is not None}


def load(
    *,
    reach: Reach,
    code: str,
    points: Sequence[PointRow],
    until: date,
) -> UnitsData:
    """Строки таблицы страны. Любой сбой чтения гасит только свой столбец."""
    if not code:
        return UnitsData()
    try:
        units = directory.list_units(reach=reach, country=code)
    except DbError:
        log.warning("Справочник пиццерий страны не прочитался", exc_info=True)
        units = []
    profiles, profiles_failed = _profiles(code)
    ratings, ratings_failed = _ratings(code, until)
    maps, maps_failed = _maps(until)
    rows = build_rows(
        units, profiles, {p.unit: p for p in points}, ratings, maps, _last_ever(reach)
    )
    return UnitsData(
        rows=rows,
        profiles_failed=profiles_failed,
        ratings_failed=ratings_failed,
        maps_failed=maps_failed,
        has_ratings=any(r.rs is not None or r.rko is not None for r in rows),
        has_maps=any(r.maps for r in rows),
    )


def history(
    *, reach: Reach, name: str, fallback: tuple[InspectionRow, ...]
) -> tuple[InspectionRow, ...]:
    """Последние проверки пиццерии за всё время; не прочиталось — те, что за период."""
    try:
        return tuple(queries.list_inspections(reach=reach, unit=name, limit=HISTORY_LIMIT))
    except DbError:
        log.warning("История проверок пиццерии не прочиталась", exc_info=True)
        return fallback
