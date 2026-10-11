"""Яндекс Еда: поиск у координат пиццерии, затем карточка заведения.

Поиск `POST eda.yandex.by/eats/v1/full-text-search/v1/search {text, location}`
отдаёт заведения, что доставляют на эту точку, ВКЛЮЧАЯ закрытые сейчас
(`available: false`). Своя точка пиццерии в своей зоне доставки всегда — если
её нет в выдаче, её нет на Яндекс Еде (сверено на Бресте 11.10.2026).
Карточка `GET /api/v2/catalog/{slug}?latitude&longitude` — оценка из 5,
число оценок и координаты точки. Нужен заголовок `x-platform: desktop_web`.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from .base import Found, Http, dig, is_dodo, number, votes_of

KEY = "yandex_eda"
# 1,5 с на проде 11.10.2026 — 12 отказов 429 на 76 пиццерий; 4 с — с запасом.
GAP_SEC = 4.0
SCALE = 5
HOST = "https://eda.yandex.by"
SEARCH = HOST + "/eats/v1/full-text-search/v1/search"
CARD = HOST + "/api/v2/catalog/{slug}?latitude={lat}&longitude={lng}"
HEADERS = {"x-platform": "desktop_web"}
#: Страны IMF, где Яндекс Еда работает и где искать Додо (сверено 11.10.2026).
COUNTRIES = frozenset({"BY", "AM", "KG"})


def places(payload: object) -> dict[str, bool | None]:
    """Заведения Додо в выдаче поиска: slug → доступно ли сейчас."""
    found: dict[str, bool | None] = {}

    def walk(node: object) -> None:
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            slug, brand = node.get("slug"), dig(node, "brand", "slug")
            if isinstance(slug, str) and isinstance(brand, str) and is_dodo(node.get("title")):
                available = node.get("available")
                found[slug] = available if isinstance(available, bool) else None
            for child in node.values():
                walk(child)

    walk(payload)
    return found


def card(payload: object, slug: str, is_open: bool | None) -> Found | None:
    place = dig(payload, "payload", "foundPlace", "place")
    if not isinstance(place, dict):
        return None
    votes, exact = votes_of(place.get("ratingCount"))
    brand = dig(place, "brand", "slug") or "dodo_picca"
    return Found(
        point_key=slug,
        name=str(place.get("name") or ""),
        url=f"{HOST}/r/{brand}?placeSlug={slug}",
        lat=number(dig(place, "address", "location", "latitude")),
        lng=number(dig(place, "address", "location", "longitude")),
        score=number(place.get("rating")),
        scale=SCALE,
        votes=votes,
        votes_exact=exact,
        is_open=is_open,
        extra={"address": dig(place, "address", "short")},
    )


def search(
    http: Http, lat: float, lng: float, country: str, cache: MutableMapping[str, object]
) -> list[Found]:
    found = []
    body = {"text": "Додо", "location": {"latitude": lat, "longitude": lng}}
    for slug, is_open in places(http.post(SEARCH, body, HEADERS)).items():
        key = f"{KEY}:{slug}"
        if key not in cache:
            cache[key] = card(
                http.get(CARD.format(slug=slug, lat=lat, lng=lng), HEADERS), slug, is_open
            )
        point = cache[key]
        if isinstance(point, Found):
            found.append(point)
    return found
