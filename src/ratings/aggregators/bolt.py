"""Bolt Food: публичный поиск заведений у координат.

`POST deliveryuser.live.boltsvc.net/deliveryClient/public/findProviders` с
координатами в ТЕЛЕ; фильтр `query` не работает — приходит весь город (до ~1200
заведений, видны и закрытые), Додо отбираем по названию. Оценка —
`rating_info.rating` из 5, `rating_info.count` — точное число. Страна или город,
где Bolt Food нет, отвечают `code 5812 CITY_NOT_FOUND` — это не сбой, а пусто.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping

from .base import AggregatorError, Found, Http, dig, is_dodo, items, number, votes_of

KEY = "bolt_food"
GAP_SEC = 2.5
SCALE = 5
CITY_NOT_FOUND = 5812
FIND = (
    "https://deliveryuser.live.boltsvc.net/deliveryClient/public/findProviders"
    "?version=FW.1.100&deviceId={device}&deviceType=web&device_name=web"
    "&device_os_version=macos&language=en-GB&country={country}&session_id=s1"
)
HEADERS = {"Origin": "https://food.bolt.eu"}
#: Страны IMF, где Bolt Food работает (сверено 11.10.2026).
COUNTRIES = frozenset({"AZ", "BG", "CY", "EE", "GE", "LT", "PL", "RO"})


def parse(payload: object) -> list[Found]:
    code = dig(payload, "code")
    if code == CITY_NOT_FOUND:
        return []
    if code not in (0, None):
        raise AggregatorError(f"Bolt Food ответил code {code}: {dig(payload, 'message')}")
    found = []
    for provider in items(payload, "data", "providers"):
        name = dig(provider, "name", "value")
        pid = dig(provider, "provider_id")
        if not is_dodo(name) or not isinstance(pid, int):
            continue
        votes, exact = votes_of(dig(provider, "rating_info", "count"))
        slug = dig(provider, "slug")
        available = dig(provider, "is_available_for_delivery")
        found.append(
            Found(
                point_key=str(pid),
                name=str(name),
                url=f"https://food.bolt.eu/en/provider/{slug}" if isinstance(slug, str) else None,
                lat=number(dig(provider, "lat")),
                lng=number(dig(provider, "lng")),
                score=number(dig(provider, "rating_info", "rating")),
                scale=SCALE,
                votes=votes,
                votes_exact=exact,
                is_open=available if isinstance(available, bool) else None,
            )
        )
    return found


def search(
    http: Http, lat: float, lng: float, country: str, cache: MutableMapping[str, object]
) -> list[Found]:
    url = FIND.format(device=uuid.uuid4(), country=country.lower())
    body = {"query": "dodo", "filters": [], "lat": lat, "lng": lng}
    return parse(http.post(url, body, HEADERS))
