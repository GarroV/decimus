"""Glovo: оценка известной точки по id магазина и координатам доставки.

**Поиск с сервера не работает** — `v3/feeds/search` и `store_wall/search`
отвечают 503 без браузера. Поэтому точка берётся из справочника привязок
(`agg.points`), наполненного разово поиском в браузере (docs/17-aggregators.md).

**Что такое точка.** Id в адресе магазина — это бренд в городе (у всех пиццерий
Бухареста он один). Какую точку показать, Glovo решает по адресу доставки:
`GET api.glovoapp.com/v3/stores/{id}` с координатами пиццерии в заголовках
отдаёт её точку — `addressId`, адрес и оценку: `ratingInfo.ratingValue`
(доля положительных, 0..1) и точное `ratingInfo.ratingCount`. Ключ точки у
нас — `addressId`. Если на те же координаты Glovo вдруг отдал другую точку —
привязка устарела, это сбой точки, а не новая оценка.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping

from src.db.agg_store import PointRow

from .base import AggregatorError, Found, Http, dig, number, votes_of

KEY = "glovo"
GAP_SEC = 2.0
SCALE = 100
STORE = "https://api.glovoapp.com/v3/stores/{store_id}"


def headers(extra: Mapping[str, object]) -> dict[str, str]:
    return {
        "Glovo-App-Platform": "web",
        "Glovo-App-Type": "customer",
        "Glovo-Language-Code": "en",
        "Glovo-Api-Version": "14",
        "Glovo-Perseus-Client-Id": "web.customer.desktop",
        "Glovo-Perseus-Session-Id": str(uuid.uuid4()),
        "Glovo-Request-Id": str(uuid.uuid4()),
        "Glovo-Location-City-Code": str(extra.get("city_code", "")),
        "Glovo-Location-Country-Code": str(extra.get("country", "")),
        "Glovo-Delivery-Location-Latitude": str(extra.get("lat", "")),
        "Glovo-Delivery-Location-Longitude": str(extra.get("lng", "")),
        "Glovo-Delivery-Location-Accuracy": "10",
        "Glovo-Delivery-Location-Timestamp": str(int(time.time() * 1000)),
    }


def parse(payload: object, point: PointRow) -> Found:
    address_id = dig(payload, "addressId")
    if str(address_id) != point.point_key:
        raise AggregatorError(
            f"Glovo отдал на координаты пиццерии другую точку "
            f"({address_id}, ждали {point.point_key})"
        )
    value = number(dig(payload, "ratingInfo", "ratingValue"))
    votes, exact = votes_of(dig(payload, "ratingInfo", "ratingCount"))
    is_open = dig(payload, "open")
    return Found(
        point_key=point.point_key,
        name=str(dig(payload, "name") or point.name or ""),
        url=point.url,
        lat=point.lat,
        lng=point.lng,
        score=None if value is None else round(value * 100, 1),
        scale=SCALE,
        votes=votes,
        votes_exact=exact,
        is_open=is_open if isinstance(is_open, bool) else None,
        extra={"address": dig(payload, "address")},
    )


def refresh(http: Http, point: PointRow) -> Found:
    store_id = point.extra.get("store_id")
    if store_id is None:
        raise AggregatorError(f"У точки Glovo {point.point_key} нет store_id в справочнике")
    return parse(http.get(STORE.format(store_id=store_id), headers(point.extra)), point)
