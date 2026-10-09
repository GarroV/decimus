"""Клиент Pointer API: сети и филиалы с текущими оценками на картах.

Только чтение и только обычные списки (`/networks`, `/companies`): суточные
экспорты (`/export/json/...`) не нужны — оценки филиала приходят в списке
(`with_ratings=1`), а у списка лимит секундный, не суточный
(docs/09-pointer-api.md). Пауза между запросами держит «не чаще раза в секунду».

Ответ — внешние данные: каждое поле проверяется, кривой филиал отбрасывается
с причиной, а не роняет всю загрузку.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pntr.io/v1"
PAGE_SIZE = 100  # максимум API
REQUEST_GAP_SEC = 1.1  # лимит Pointer — не чаще раза в секунду
TIMEOUT_SEC = 30
MAX_PAGES = 50  # предохранитель от бесконечной пагинации: 5000 филиалов

#: Карты, которые показываем. Остальные провайдеры (Tripadvisor, 2ГИС и т. д.)
#: хранятся, но на страницу не выходят.
GOOGLE = 2
YANDEX = 1


class PointerError(RuntimeError):
    """Pointer не ответил или ответил не тем. Сообщение — без ключа."""


@dataclass(frozen=True)
class Rating:
    provider_id: int
    on_date: date
    avg_rating: float
    ratings_count: int


@dataclass(frozen=True)
class Company:
    uuid: str
    network_uuid: str | None
    network_name: str | None
    name: str
    country_code: str | None
    city: str | None
    address: str | None
    lat: float | None
    lng: float | None
    status_type_id: int | None
    pointer_link: str | None
    ratings: tuple[Rating, ...]


Fetch = Callable[[str], Mapping[str, Any]]


def http_fetch(key: str) -> Fetch:
    """Запрос с ключом и паузой. Ключ живёт только в заголовке."""

    def fetch(path: str) -> Mapping[str, Any]:
        time.sleep(REQUEST_GAP_SEC)
        request = urllib.request.Request(  # noqa: S310 — адрес постоянный, https
            BASE_URL + path, headers={"Authorization": f"Bearer {key}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            raise PointerError(f"Pointer ответил {exc.code} на {path.split('?')[0]}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PointerError(f"Pointer недоступен ({exc.__class__.__name__})") from exc
        if not isinstance(body, dict):
            raise PointerError(f"Pointer вернул не объект на {path.split('?')[0]}")
        return body

    return fetch


def _pages(fetch: Fetch, path: str) -> Iterator[Mapping[str, Any]]:
    joiner = "&" if "?" in path else "?"
    for page in range(MAX_PAGES):
        body = fetch(f"{path}{joiner}limit={PAGE_SIZE}&offset={page * PAGE_SIZE}")
        items = body.get("items")
        if not isinstance(items, list):
            raise PointerError(f"В ответе {path} нет списка items")
        yield from (item for item in items if isinstance(item, dict))
        total = (body.get("meta") or {}).get("total")
        if not isinstance(total, int) or (page + 1) * PAGE_SIZE >= total:
            return
    raise PointerError(f"{path}: больше {MAX_PAGES} страниц — остановлено")


def _text(value: object, limit: int = 300) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _rating(raw: Mapping[str, Any]) -> Rating | None:
    provider, count, avg = (
        raw.get("provider_id"),
        raw.get("ratings_count"),
        _number(raw.get("avg_rating")),
    )
    try:
        on_date = date.fromisoformat(str(raw.get("date")))
    except ValueError:
        return None
    if not isinstance(provider, int) or not isinstance(count, int) or avg is None:
        return None
    if not 0 <= avg <= 5 or count < 0:
        return None
    return Rating(provider, on_date, avg, count)


def parse_company(raw: Mapping[str, Any], networks: Mapping[str, str]) -> Company | None:
    """Филиал из ответа или `None`, если без идентификатора или имени."""
    uuid, name = _text(raw.get("uuid"), 64), _text(raw.get("name"), 200)
    if uuid is None or name is None:
        return None
    country = _text(raw.get("country_code"), 2)
    address_raw = raw.get("address_fields")
    address: Mapping[str, Any] = address_raw if isinstance(address_raw, dict) else {}
    ratings_raw = raw.get("ratings")
    ratings: list[Any] = ratings_raw if isinstance(ratings_raw, list) else []
    network = _text(raw.get("network_uuid"), 64)
    status = raw.get("status_type_id")
    return Company(
        uuid=uuid,
        network_uuid=network,
        network_name=networks.get(network or ""),
        name=name,
        country_code=country.upper()
        if country and len(country) == 2 and country.isalpha()
        else None,
        city=_text(address.get("city"), 120),
        address=_text(raw.get("full_address")),
        lat=_number(raw.get("lat")),
        lng=_number(raw.get("lng")),
        status_type_id=status if isinstance(status, int) else None,
        pointer_link=_text(raw.get("pointer_link")),
        ratings=tuple(r for r in (_rating(x) for x in ratings if isinstance(x, dict)) if r),
    )


def companies(fetch: Fetch) -> tuple[Company, ...]:
    """Все филиалы, видимые ключу, с оценками. Сети — ради названия сети.

    Филиал из `/companies` не несёт сеть, поэтому сеть берётся проходом по
    сетям: `/companies?network_uuid=…` для каждой. Запросов — сети плюс
    страницы, для 21 сети около 25.
    """
    networks = {
        str(n["uuid"]): str(n.get("name") or "")
        for n in _pages(fetch, "/networks")
        if isinstance(n.get("uuid"), str)
    }
    found: dict[str, Company] = {}
    skipped = 0
    for network_uuid in networks:
        path = f"/companies?network_uuid={network_uuid}&with_ratings=1"
        for raw in _pages(fetch, path):
            company = parse_company({**raw, "network_uuid": network_uuid}, networks)
            if company is None:
                skipped += 1
                continue
            found[company.uuid] = company
    if skipped:
        logger.warning("Pointer: пропущено филиалов без идентификатора или имени: %d", skipped)
    return tuple(found.values())
