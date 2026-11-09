"""Trendyol Go (бывший Trendyol Yemek, Турция): подсказки поиска и карточка.

Поиск `restaurants/in/search` прячет закрытые сейчас заведения, поэтому —
подсказки `suggestions?text=dodo&latitude&longitude` (их не прячут), затем
карточка `restaurants/{id}`: оценка — среднее трёх оценок `score.flavor`,
`score.service`, `score.delivery` (D737; нет каких-то — среднее имеющихся, нет
ни одной — `score.overall`), из 5, число оценок
ступенью (`score.ratingText`, «(1500+)»), координаты `location.point`
(«lat,lng»), статус. Нужны заголовки Origin и Referer сайта.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from .base import Found, Http, dig, is_dodo, items, number, votes_of

KEY = "trendyol_go"
GAP_SEC = 2.0
SCALE = 5
API = "https://api.tgoapis.com"
SUGGEST = (
    API + "/web-discovery-apidiscovery-santral/suggestions?text=dodo&latitude={lat}&longitude={lng}"
)
CARD = API + "/web-restaurant-apirestaurant-santral/restaurants/{id}?latitude={lat}&longitude={lng}"
HEADERS = {"Origin": "https://tgoyemek.com", "Referer": "https://tgoyemek.com/"}
COUNTRIES = frozenset({"TR"})


def suggested_ids(payload: object) -> list[int]:
    ids = []
    for group in items(payload, "suggestions"):
        for item in items(group, "items"):
            rid = dig(item, "restaurantId")
            if (
                isinstance(rid, int)
                and is_dodo(dig(item, "name") or dig(item, "title") or "Dodo Pizza")
                and rid not in ids
            ):
                ids.append(rid)
    return ids


PARTS = ("flavor", "service", "delivery")


def blended_score(info: dict[str, object]) -> float | None:
    """Среднее вкуса, сервиса и доставки (D737); иначе общая `overall`."""
    parts = [v for v in (number(dig(info, "score", p)) for p in PARTS) if v is not None]
    if not parts:
        return number(dig(info, "score", "overall"))
    return round(sum(parts) / len(parts), 2)


def card(payload: object) -> Found | None:
    info = dig(payload, "restaurant", "info")
    if (
        not isinstance(info, dict)
        or not is_dodo(info.get("name"))
        or not isinstance(info.get("id"), int)
    ):
        return None
    point = dig(info, "location", "point")
    lat, lng = point.split(",", 1) if isinstance(point, str) and "," in point else (None, None)
    votes, exact = votes_of(dig(info, "score", "ratingText"))
    status = info.get("status")
    return Found(
        point_key=str(info["id"]),
        name=str(info["name"]),
        url=f"https://tgoyemek.com/restoranlar/{info['id']}",
        lat=number(lat),
        lng=number(lng),
        score=blended_score(info),
        scale=SCALE,
        votes=votes,
        votes_exact=exact,
        is_open=None if not isinstance(status, str) else status != "CLOSED",
        extra={"comments": info.get("commentCount"), "address": dig(info, "location", "address")},
    )


def search(
    http: Http, lat: float, lng: float, country: str, cache: MutableMapping[str, object]
) -> list[Found]:
    found = []
    for rid in suggested_ids(http.get(SUGGEST.format(lat=lat, lng=lng), HEADERS)):
        key = f"{KEY}:{rid}"
        if key not in cache:
            cache[key] = card(http.get(CARD.format(id=rid, lat=lat, lng=lng), HEADERS))
        point = cache[key]
        if isinstance(point, Found):
            found.append(point)
    return found
