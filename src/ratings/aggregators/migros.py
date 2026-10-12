"""Migros Yemek (Турция): оценка известной точки по адресу её страницы.

`GET www.migros.com.tr/rest/food-bff/api/stores/{prettyNameUrl}` без входа и
ключа (адрес API — в открытом `env.js` сайта, `foodBffBaseUrl`). Адресу сервера
площадки Migros отвечает 403 целиком, поэтому запрос идёт через ретранслятор на
домашнем сервере (`migros_relay.py`, D434): `MIGROS_RELAY_URL` — его адрес в сети
Tailscale; не задан — сбор Migros падает с этой причиной, а не молчит. `storeDTO.rating`
— `score` из 5 строкой с запятой («4,5») и точное `commentCount`. Координат и
признака «открыто сейчас» карточка не отдаёт, поэтому точки — из справочника
привязок (docs/17-aggregators.md), как у Chowdeck.
"""

from __future__ import annotations

import os

from src.db.agg_store import PointRow

from .base import AggregatorError, Found, Http, dig, is_dodo, number, votes_of

KEY = "migros_yemek"
GAP_SEC = 2.0
SCALE = 5
RELAY_VAR = "MIGROS_RELAY_URL"
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


def store_url(slug: str, relay: str | None = None) -> str:
    """Адрес карточки точки у ретранслятора."""
    base = (relay if relay is not None else os.environ.get(RELAY_VAR, "")).strip().rstrip("/")
    if not base:
        raise AggregatorError(f"Migros: не задан {RELAY_VAR} — ретранслятор на домашнем сервере")
    return f"{base}/stores/{slug}"


def reason(exc: AggregatorError) -> str:
    """Причина сбоя словами и без адреса ретранслятора: текст уходит в журнал
    на странице рейтингов и в уведомление."""
    code = str(exc).split(" — ")[0]
    if code.startswith("HTTP "):
        return f"Migros ответил {code} (через домашний сервер)"
    return f"домашний сервер не отвечает ({code})"


def refresh(http: Http, point: PointRow) -> Found:
    url = store_url(point.point_key)  # не задан ретранслятор — своя причина, не «не отвечает»
    try:
        payload = http.get(url)
    except AggregatorError as exc:
        raise AggregatorError(reason(exc)) from exc
    return parse(payload, point)
