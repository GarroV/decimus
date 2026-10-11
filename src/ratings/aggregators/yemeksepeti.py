"""Yemeksepeti (Delivery Hero, Турция): витрина заведений у координат.

`GET disco.deliveryhero.io/listing/api/v1/pandora/vendors?latitude&longitude
&country=tr&limit=500` с заголовком `x-disco-client-id: web`; параметр поиска
ответ игнорирует — Додо отбираем по названию. Оценка — `rating` из 5, число
отзывов `review_number` точное, координаты — `latitude/longitude`.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from .base import Found, Http, dig, is_dodo, number, votes_of

KEY = "yemeksepeti"
GAP_SEC = 2.0
SCALE = 5
VENDORS = (
    "https://disco.deliveryhero.io/listing/api/v1/pandora/vendors?latitude={lat}&longitude={lng}"
    "&language_id=2&configuration=Variant1&country=tr&customer_type=regular&limit={limit}&offset={offset}"
    "&language_code=tr&vertical=restaurants&opening_type=delivery"
)
HEADERS = {"x-disco-client-id": "web"}
COUNTRIES = frozenset({"TR"})
PAGE = 500
MAX_PAGES = 4  # большие города — до ~1200 заведений; закрытые сейчас идут в конце списка


def parse(payload: object) -> list[Found]:
    items = payload.get("data", {}).get("items") if isinstance(payload, dict) else None
    found = []
    for vendor in items or []:
        if not isinstance(vendor, dict) or not is_dodo(vendor.get("name")):
            continue
        code = vendor.get("code")
        if not isinstance(code, str) or not code:
            continue
        votes, exact = votes_of(vendor.get("review_number"))
        active = vendor.get("is_active")
        found.append(
            Found(
                point_key=code,
                name=str(vendor["name"]),
                url=vendor.get("redirection_url")
                if isinstance(vendor.get("redirection_url"), str)
                else None,
                lat=number(vendor.get("latitude")),
                lng=number(vendor.get("longitude")),
                score=number(vendor.get("rating")),
                scale=SCALE,
                votes=votes,
                votes_exact=exact,
                is_open=active if isinstance(active, bool) else None,
                extra={"address": vendor.get("address")},
            )
        )
    return found


def search(
    http: Http, lat: float, lng: float, country: str, cache: MutableMapping[str, object]
) -> list[Found]:
    """Все страницы витрины: закрытые сейчас заведения стоят в конце, и Додо в
    большом городе бывает за первой сотней — лимит страницы 500."""
    found: list[Found] = []
    for page in range(MAX_PAGES):
        payload = http.get(
            VENDORS.format(lat=lat, lng=lng, limit=PAGE, offset=page * PAGE), HEADERS
        )
        found += parse(payload)
        total = dig(payload, "data", "available_count")
        if not isinstance(total, int) or (page + 1) * PAGE >= total:
            break
    return found
