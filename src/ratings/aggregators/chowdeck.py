"""Chowdeck (Нигерия): оценка известной точки по id заведения.

`GET api.chowdeck.com/customer/vendor/{id}` без авторизации: `average_rating`
из 5 (строкой), точное `number_of_rating`, координаты `coordinate {x: lon,
y: lat}`, `is_active`. Поиск без адреса доставки пуст, поэтому точки — из
справочника привязок (docs/17-aggregators.md).
"""

from __future__ import annotations

from src.db.agg_store import PointRow

from .base import AggregatorError, Found, Http, dig, is_dodo, number, votes_of

KEY = "chowdeck"
GAP_SEC = 1.5
SCALE = 5
VENDOR = "https://api.chowdeck.com/customer/vendor/{id}"


def parse(payload: object, point: PointRow) -> Found:
    vendor = dig(payload, "data")
    if not isinstance(vendor, dict) or not is_dodo(vendor.get("name")):
        raise AggregatorError(f"Chowdeck: заведение {point.point_key} не найдено или уже не Додо")
    votes, exact = votes_of(vendor.get("number_of_rating"))
    active = vendor.get("is_active")
    return Found(
        point_key=point.point_key,
        name=str(vendor["name"]),
        url=point.url,
        lat=number(dig(vendor, "coordinate", "y")),
        lng=number(dig(vendor, "coordinate", "x")),
        score=number(vendor.get("average_rating")),
        scale=SCALE,
        votes=votes,
        votes_exact=exact,
        is_open=active if isinstance(active, bool) else None,
    )


def refresh(http: Http, point: PointRow) -> Found:
    return parse(http.get(VENDOR.format(id=point.point_key)), point)
