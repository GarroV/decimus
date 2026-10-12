"""Migros Yemek (Турция): оценка известной точки по адресу её страницы.

`GET www.migros.com.tr/rest/food-bff/api/stores/{prettyNameUrl}` без входа и
ключа (адрес API — в открытом `env.js` сайта, `foodBffBaseUrl`): `storeDTO.rating`
— `score` из 5 строкой с запятой («4,5») и точное `commentCount`. Координат и
признака «открыто сейчас» карточка не отдаёт, поэтому точки — из справочника
привязок (docs/17-aggregators.md), как у Chowdeck.
"""

from __future__ import annotations

from src.db.agg_store import PointRow

from .base import AggregatorError, Found, Http, dig, is_dodo, number, votes_of

KEY = "migros_yemek"
GAP_SEC = 2.0
SCALE = 5
STORE = "https://www.migros.com.tr/rest/food-bff/api/stores/{slug}"
PAGE = "https://www.migros.com.tr/yemek/{slug}"


def parse(payload: object, point: PointRow) -> Found:
    store = dig(payload, "storeDTO")
    if not isinstance(store, dict) or not is_dodo(store.get("title")):
        raise AggregatorError(f"Migros: заведение {point.point_key} не найдено или уже не Додо")
    votes, exact = votes_of(dig(store, "rating", "commentCount"))
    return Found(
        point_key=point.point_key,
        name=str(store["title"]),
        url=PAGE.format(slug=point.point_key),
        lat=None,
        lng=None,
        score=number(dig(store, "rating", "score")),
        scale=SCALE,
        votes=votes,
        votes_exact=exact,
        is_open=None,
        extra={"store_id": store.get("id"), "city_id": store.get("cityId")},
    )


def refresh(http: Http, point: PointRow) -> Found:
    return parse(http.get(STORE.format(slug=point.point_key)), point)
