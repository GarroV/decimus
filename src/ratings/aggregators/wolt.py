"""Wolt: каталог заведений у координат пиццерии.

`GET restaurant-api.wolt.com/v1/pages/restaurants?lat&lon` — все заведения,
что доставляют на эту точку, ВКЛЮЧАЯ закрытые сейчас (поле `online`); поиск
`/v1/pages/search` закрытые прячет, поэтому не он. Оценка — `rating.score` из
10 и точное число `rating.volume`; координаты — `location: [lon, lat]`.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from .base import Found, Http, dig, is_dodo, items, number, votes_of

KEY = "wolt"
GAP_SEC = 2.5
SCALE = 10
CATALOG = "https://restaurant-api.wolt.com/v1/pages/restaurants?lat={lat}&lon={lng}"
#: Страны IMF, где Wolt работает (сверено 11.10.2026); ISO-3 нужен для ссылки.
COUNTRIES = {
    "AZ": "aze", "BG": "bgr", "CY": "cyp", "EE": "est", "GE": "geo", "HR": "hrv",
    "LT": "ltu", "PL": "pol", "RO": "rou", "RS": "srb", "SI": "svn",
}  # fmt: skip


def parse(payload: object, country: str) -> list[Found]:
    found = []
    for section in items(payload, "sections"):
        for item in items(section, "items"):
            venue = dig(item, "venue")
            if not isinstance(venue, dict) or not is_dodo(venue.get("name")):
                continue
            slug, where = venue.get("slug"), venue.get("location")
            if not isinstance(slug, str) or not slug:
                continue
            lng, lat = where if isinstance(where, list) and len(where) == 2 else (None, None)
            votes, exact = votes_of(dig(venue, "rating", "volume"))
            online = venue.get("online")
            found.append(
                Found(
                    point_key=slug,
                    name=str(venue["name"]),
                    url=f"https://wolt.com/en/{COUNTRIES.get(country, 'x')}/x/restaurant/{slug}",
                    lat=number(lat),
                    lng=number(lng),
                    score=number(dig(venue, "rating", "score")),
                    scale=SCALE,
                    votes=votes,
                    votes_exact=exact,
                    is_open=online if isinstance(online, bool) else None,
                    extra={"venue_id": venue.get("id")},
                )
            )
    return found


def search(
    http: Http, lat: float, lng: float, country: str, cache: MutableMapping[str, object]
) -> list[Found]:
    return parse(http.get(CATALOG.format(lat=lat, lng=lng)), country)
