"""Pyszne.pl (Just Eat Takeaway, Польша): витрина у координат.

`GET rest.api.eu-central-1.production.jet-external.com/discovery/pl/restaurants/
enriched?latitude&longitude` с заголовком `Accept-Tenant: pl` — сотни
заведений вокруг, включая закрытые; сам сайт pyszne.pl закрыт защитой, этот
хост — нет. Оценка — `rating.starRating` из 5, `rating.count` точное,
координаты — `address.location.coordinates: [lon, lat]`.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from .base import Found, Http, dig, is_dodo, items, number, votes_of

KEY = "pyszne_pl"
GAP_SEC = 2.0
SCALE = 5
ENRICHED = (
    "https://rest.api.eu-central-1.production.jet-external.com/discovery/pl/restaurants/enriched"
    "?latitude={lat}&longitude={lng}"
)
HEADERS = {"Accept-Tenant": "pl"}
COUNTRIES = frozenset({"PL"})


def parse(payload: object) -> list[Found]:
    found = []
    for shop in items(payload, "restaurants"):
        if not isinstance(shop, dict) or not is_dodo(shop.get("name")):
            continue
        unique = shop.get("uniqueName")
        if not isinstance(unique, str) or not unique:
            continue
        where = dig(shop, "address", "location", "coordinates")
        lng, lat = where if isinstance(where, list) and len(where) == 2 else (None, None)
        votes, exact = votes_of(dig(shop, "rating", "count"))
        is_open = dig(shop, "availability", "delivery", "isOpen")
        found.append(
            Found(
                point_key=unique,
                name=str(shop["name"]),
                url=f"https://www.pyszne.pl/menu/{unique}",
                lat=number(lat),
                lng=number(lng),
                score=number(dig(shop, "rating", "starRating")),
                scale=SCALE,
                votes=votes,
                votes_exact=exact,
                is_open=is_open if isinstance(is_open, bool) else None,
                extra={"id": shop.get("id")},
            )
        )
    return found


def search(
    http: Http, lat: float, lng: float, country: str, cache: MutableMapping[str, object]
) -> list[Found]:
    return parse(http.get(ENRICHED.format(lat=lat, lng=lng), HEADERS))
