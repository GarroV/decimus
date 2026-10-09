"""Связь филиала Pointer с пиццерией Dodo — по координатам.

У Pointer нет нашего кода пиццерии, зато у филиала есть координаты, а у
пиццерии Dodo они есть в публичном API (`publicapi.dodois.io`). Филиал
связывается с ближайшей пиццерией: сразу — если она не дальше `NEAR_M`; до
`FAR_M` — если совпадение однозначное, то есть следующая пиццерия хотя бы в
`CLEAR_RATIO` раз дальше. Метка на карте бывает неточной на сотни метров, а
пиццерии Dodo стоят минимум в нескольких кварталах друг от друга (владелец,
09.10.2026) — поэтому ближайшая при большом отрыве и есть та самая.
Пиццерия достаётся одному филиалу — ближайшему: два филиала на одной точке
(дубль карточки на карте) не делят её оценку.

Публичный API — внешние данные: пиццерия без кода или координат отбрасывается.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PUBLIC_API = "https://publicapi.dodois.io/{country}/api/v1/unitinfo/all"
PIZZERIA_TYPE = 1  # у Dodo `Type == 1` — пиццерия; 0 — офис
NEAR_M = 300
FAR_M = 1500
CLEAR_RATIO = 2.0
REQUEST_GAP_SEC = 0.5
TIMEOUT_SEC = 30
EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class DodoUnit:
    dodo_id: str
    name: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Point:
    uuid: str
    lat: float
    lng: float


@dataclass(frozen=True)
class Link:
    company_uuid: str
    dodo_id: str
    dodo_name: str
    distance_m: int


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Расстояние по поверхности Земли (гаверсинус), метры."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def match(points: Sequence[Point], units: Sequence[DodoUnit]) -> tuple[Link, ...]:
    """Филиал → ближайшая пиццерия (правило — в описании модуля); пиццерия —
    одному филиалу, ближайшему."""
    candidates: list[Link] = []
    for point in points:
        near = sorted(
            ((distance_m(point.lat, point.lng, u.lat, u.lng), u) for u in units),
            key=lambda pair: pair[0],
        )[:2]
        if not near:
            continue
        (best, unit), runner_up = near[0], (near[1][0] if len(near) > 1 else math.inf)
        if best <= NEAR_M or (best <= FAR_M and runner_up >= CLEAR_RATIO * best):
            candidates.append(Link(point.uuid, unit.dodo_id, unit.name, round(best)))
    taken: dict[str, Link] = {}
    for link in sorted(candidates, key=lambda c: c.distance_m):
        taken.setdefault(link.dodo_id, link)
    return tuple(taken.values())


def parse_units(payload: object) -> tuple[DodoUnit, ...]:
    """Пиццерии из ответа публичного API; кривые записи отбрасываются."""
    if not isinstance(payload, list):
        return ()
    found = []
    for raw in payload:
        if not isinstance(raw, dict) or raw.get("Type") != PIZZERIA_TYPE:
            continue
        uuid, name, where = raw.get("UUId"), raw.get("Name"), raw.get("Location")
        if not isinstance(uuid, str) or len(uuid) != 32 or not isinstance(where, dict):
            continue
        lat, lng = where.get("Latitude"), where.get("Longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            continue
        if lat == 0 and lng == 0:
            continue
        found.append(DodoUnit(uuid.lower(), str(name or ""), float(lat), float(lng)))
    return tuple(found)


def fetch_units(countries: Iterable[str]) -> tuple[DodoUnit, ...]:
    """Пиццерии Dodo по странам из публичного API. Страна, которой API не
    знает или не ответил, пропускается с записью в журнал — остальные идут."""
    found: list[DodoUnit] = []
    for country in sorted({c.lower() for c in countries if c}):
        url = PUBLIC_API.format(country=country)
        time.sleep(REQUEST_GAP_SEC)
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as response:  # noqa: S310
                found.extend(parse_units(json.load(response)))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("Публичный API Dodo: страна %s не прочиталась (%s)", country, exc)
    return tuple(found)
