"""Glovo: новые точки находятся сами или привязываются по ссылке (D424, #648).

**Автопоиск.** Id магазина Glovo — бренд в городе, а конкретную точку Glovo
выбирает по координатам доставки (`glovo.py`). Поэтому пиццерия, у которой ещё
нет точки, спрашивается тем же запросом, что и известная: берём ближайшую
известную точку той же страны не дальше `DONOR_MAX_M` (её `store_id` и
`city_code`), подставляем координаты самой пиццерии и смотрим, какую точку
отдал Glovo. Новый `addressId` — это точка пиццерии, она записывается; тот, что
уже есть в справочнике, — пиццерия либо не на Glovo, либо покрыта чужой точкой,
пропускаем. Решения — чистые функции (`choose_donor`, `accepts`), сеть — снаружи.

**Привязка по ссылке** — для первой пиццерии нового города, где известной точки
рядом нет. Человек даёт страницу магазина `https://glovoapp.com/<язык>/<страна>/
<город>/stores/<магазин>`; сервер читает с неё `store_id` и `cityCode` и дальше
идёт тем же запросом. Адрес проверяется строго, а страница читается без
редиректов: сервер не должен ходить никуда, кроме `glovoapp.com` (SSRF).
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol
from urllib.parse import urlsplit

from src.db.agg_store import PointRow, RatingRow
from src.ratings.maps_link import distance_m

from . import glovo
from .base import TIMEOUT_SEC, USER_AGENT, AggregatorError, Http, dig

logger = logging.getLogger(__name__)

DONOR_MAX_M = 40_000
HOST = "glovoapp.com"
PAGE_MAX_BYTES = 3_000_000
_PATH = re.compile(
    r"^/(?P<lang>[a-z]{2}(?:-[a-z]{2})?)/(?P<cc>[a-z]{2})/(?P<city>[a-z0-9-]+)"
    r"/stores/(?P<slug>[a-z0-9][a-z0-9._%-]*)/?$"
)
_STORE_ID = re.compile(r"/v4/stores/(\d+)/addresses/\d+/")
_CITY_CODE = re.compile(r'cityCode\\?"\s*:\s*\\?"([A-Z0-9]+)')

# Коды итога привязки по ссылке — тексты `ratings.coverage.link.<код>`.
OK = "ok"
BAD_URL = "bad_url"
UNKNOWN_UNIT = "unknown_unit"
COUNTRY_MISMATCH = "country_mismatch"
PAGE_FAILED = "page_failed"
NO_STORE = "no_store"
GLOVO_FAILED = "glovo_failed"
TAKEN = "taken"


class Locatable(Protocol):
    """Пиццерия, как её видит поиск: `DodoUnit` и `agg_store.UnitRow` подходят."""

    @property
    def dodo_id(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def lat(self) -> float: ...
    @property
    def lng(self) -> float: ...
    @property
    def country(self) -> str: ...
    @property
    def working(self) -> bool: ...


@dataclass(frozen=True)
class LinkResult:
    code: str
    point_key: str | None = None


def _coords(point: PointRow) -> tuple[float, float] | None:
    """Где стоит известная точка: координаты доставки из справочника, иначе её собственные."""
    lat = point.extra.get("lat", point.lat)
    lng = point.extra.get("lng", point.lng)
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
        return float(lat), float(lng)
    return None


def choose_donor(
    unit: Locatable, known: Sequence[PointRow], max_m: float = DONOR_MAX_M
) -> PointRow | None:
    """Ближайшая известная точка той же страны не дальше `max_m` и с `store_id`
    и `city_code` в справочнике — их мы возьмём в запрос; иначе `None`."""
    best: tuple[float, PointRow] | None = None
    for point in known:
        where = _coords(point)
        if (
            point.country_code != unit.country
            or where is None
            or not point.extra.get("store_id")
            or not point.extra.get("city_code")
        ):
            continue
        metres = distance_m(unit.lat, unit.lng, *where)
        if metres <= max_m and (best is None or metres < best[0]):
            best = (metres, point)
    return best[1] if best else None


def accepts(address_id: object, taken: Collection[str]) -> bool:
    """Новая ли точка: ответ Glovo с `addressId`, которого в справочнике ещё нет."""
    return address_id is not None and str(address_id) not in taken


def _extra(
    unit: Locatable, store_id: object, city_code: object, country: object
) -> dict[str, object]:
    return {
        "store_id": store_id,
        "city_code": city_code,
        "country": country,
        "lat": unit.lat,
        "lng": unit.lng,
    }


def new_point(unit: Locatable, extra: Mapping[str, object], payload: object) -> PointRow:
    """Точка пиццерии из ответа Glovo на её координаты. Расстояния до точки нет —
    Glovo координат точки не отдаёт."""
    address_id = dig(payload, "addressId")
    if address_id is None:
        raise AggregatorError("Glovo не отдал addressId")
    return PointRow(
        glovo.KEY,
        str(address_id),
        unit.country,
        str(dig(payload, "name") or "") or None,
        None,
        unit.lat,
        unit.lng,
        unit.dodo_id,
        unit.name,
        None,
        dict(extra),
    )


def _probe(
    http: Http, unit: Locatable, extra: Mapping[str, object], taken: Collection[str], today: date
) -> tuple[PointRow, RatingRow | None] | None:
    """Спросить Glovo про пиццерию; `None` — точка уже занята другой пиццерией."""
    payload = http.get(glovo.STORE.format(store_id=extra["store_id"]), glovo.headers(extra))
    point = new_point(unit, extra, payload)
    if not accepts(point.point_key, taken):
        return None
    found = glovo.parse(payload, point)
    if found.score is None or not 0 <= found.score <= found.scale:
        return point, None
    return point, RatingRow(
        glovo.KEY,
        point.point_key,
        today,
        found.score,
        found.scale,
        found.votes,
        found.votes_exact,
        found.is_open,
    )


def discover(
    http: Http,
    units: Sequence[Locatable],
    known: Sequence[PointRow],
    taken: Collection[str],
    today: date,
) -> tuple[list[PointRow], list[RatingRow]]:
    """Точки Glovo для работающих пиццерий без неё в странах, где Glovo уже есть.
    Ошибка по одной пиццерии — в журнал, остальные идут."""
    countries = {p.country_code for p in known}
    linked = {p.dodo_id for p in known if p.dodo_id}
    seen = set(taken)
    points: list[PointRow] = []
    ratings: list[RatingRow] = []
    for unit in units:
        if not unit.working or unit.country not in countries or unit.dodo_id in linked:
            continue
        donor = choose_donor(unit, known)
        if donor is None:
            continue
        extra = _extra(
            unit, donor.extra["store_id"], donor.extra["city_code"], donor.extra.get("country")
        )
        try:
            found = _probe(http, unit, extra, seen, today)
        except AggregatorError as exc:
            logger.warning("glovo: поиск точки для %s не удался (%s)", unit.name, exc)
            continue
        if found is None:
            continue
        point, rating = found
        seen.add(point.point_key)
        points.append(point)
        if rating:
            ratings.append(rating)
        logger.info("glovo: найдена точка %s для %s", point.point_key, unit.name)
    return points, ratings


def parse_store_url(url: str) -> tuple[str, str] | None:
    """Адрес страницы магазина Glovo → (страна ISO-2 заглавными, адрес для чтения)
    или `None`. Только https, хост ровно `glovoapp.com`, без порта и логина,
    путь `/<язык>/<страна>/<город>/stores/<магазин>`; запрос и якорь отбрасываются.
    Адрес для чтения собирается из проверенных частей, а не берётся как есть."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    match = _PATH.match(parts.path)
    if (
        parts.scheme != "https"
        or parts.hostname != HOST
        or port is not None
        or parts.username
        or parts.password
        or not match
    ):
        return None
    fetch = f"https://{HOST}/{match['lang']}/{match['cc']}/{match['city']}/stores/{match['slug']}"
    return match["cc"].upper(), fetch


def store_from_page(html: str) -> tuple[str, str]:
    """`(store_id, city_code)` со страницы магазина Glovo."""
    store = _STORE_ID.search(html)
    city = _CITY_CODE.search(html)
    if not store or not city:
        raise AggregatorError("На странице Glovo нет id магазина или кода города")
    return store.group(1), city.group(1)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


def fetch_page(url: str) -> str:
    """Страница магазина как есть, без редиректов (адрес уже проверен `parse_store_url`)."""
    request = urllib.request.Request(  # noqa: S310 — хост и схема проверены выше
        url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=TIMEOUT_SEC) as resp:
            body: bytes = resp.read(PAGE_MAX_BYTES)
        return body.decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise AggregatorError(f"Страница Glovo не открылась ({exc.__class__.__name__})") from exc


def link_by_url(
    unit: Locatable | None,
    url: str,
    taken: Collection[str],
    today: date,
    *,
    http: Http | None = None,
    page: Callable[[str], str] = fetch_page,
) -> tuple[LinkResult, PointRow | None, RatingRow | None]:
    """Привязать пиццерию к Glovo по ссылке на страницу магазина. Вернуть итог
    (`LinkResult.code` — ключ текста), точку и оценку для записи."""
    if unit is None:
        return LinkResult(UNKNOWN_UNIT), None, None
    parsed = parse_store_url(url)
    if parsed is None:
        return LinkResult(BAD_URL), None, None
    country, fetch = parsed
    if country != unit.country:
        return LinkResult(COUNTRY_MISMATCH), None, None
    try:
        html = page(fetch)
    except AggregatorError as exc:
        logger.warning("glovo: страница %s не открылась (%s)", fetch, exc)
        return LinkResult(PAGE_FAILED), None, None
    try:
        store_id, city_code = store_from_page(html)
    except AggregatorError:
        return LinkResult(NO_STORE), None, None
    try:
        found = _probe(
            http or Http(glovo.GAP_SEC),
            unit,
            _extra(unit, store_id, city_code, country),
            taken,
            today,
        )
    except AggregatorError as exc:
        logger.warning("glovo: %s по ссылке не ответил (%s)", unit.name, exc)
        return LinkResult(GLOVO_FAILED), None, None
    if found is None:
        return LinkResult(TAKEN), None, None
    point, rating = found
    return LinkResult(OK, point.point_key), point, rating
