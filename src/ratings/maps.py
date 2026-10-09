"""Оценки на картах: загрузка из Pointer и сводка по странам для страницы рейтингов.

**Как считается оценка страны.** Средняя по всем отзывам страны на этой карте:
оценка каждого филиала взвешивается числом его отзывов. Так «4,8 по трём
отзывам» не перевешивает «4,2 по тысяче» — ровно то, что гость видит, листая
карту. Филиал без отзывов (0 отзывов, оценка 0) в среднее не входит, но в
счёт филиалов страны входит.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from src.db import maps_store
from src.db.maps_store import LatestRating

from . import pointer

logger = logging.getLogger(__name__)

KEY_ENV = "POINTER_API_KEY"
SHOWN_PROVIDERS = (pointer.GOOGLE, pointer.YANDEX)


@dataclass(frozen=True)
class MapScore:
    avg: float | None  # None — отзывов на этой карте нет
    reviews: int
    branches: int  # филиалов страны на этой карте, с отзывами или без


@dataclass(frozen=True)
class CountryMaps:
    country: str
    scores: dict[int, MapScore]  # карта → оценка
    as_of: date | None


def summarize(rows: Iterable[LatestRating], countries: Sequence[str]) -> tuple[CountryMaps, ...]:
    """Сводка по странам в их порядке; страна без филиалов — с пустыми оценками."""
    acc: dict[tuple[str, int], list[LatestRating]] = {}
    for row in rows:
        acc.setdefault((row.country_code, row.provider_id), []).append(row)
    result = []
    for country in countries:
        scores: dict[int, MapScore] = {}
        dates: list[date] = []
        for provider in SHOWN_PROVIDERS:
            items = acc.get((country, provider), [])
            reviews = sum(r.ratings_count for r in items)
            weighted = sum(r.avg_rating * r.ratings_count for r in items)
            scores[provider] = MapScore(
                round(weighted / reviews, 2) if reviews else None, reviews, len(items)
            )
            dates += [r.on_date for r in items]
        result.append(CountryMaps(country, scores, max(dates) if dates else None))
    return tuple(result)


def load_once(fetch: pointer.Fetch | None = None) -> tuple[int, int]:
    """Забрать сети и филиалы с оценками и записать снимок. След — в журнале загрузок."""
    if fetch is None:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key:
            raise pointer.PointerError(f"{KEY_ENV} не задан — загрузка оценок карт выключена")
        fetch = pointer.http_fetch(key)
    try:
        found = pointer.companies(fetch)
        companies = [
            (
                c.uuid,
                c.network_uuid,
                c.network_name,
                c.name,
                c.country_code,
                c.city,
                c.address,
                c.lat,
                c.lng,
                c.status_type_id,
                c.pointer_link,
            )
            for c in found
        ]
        ratings = [
            (c.uuid, r.provider_id, r.on_date, r.avg_rating, r.ratings_count)
            for c in found
            for r in c.ratings
        ]
        saved = maps_store.save(companies, ratings)
    except Exception as exc:
        maps_store.log_load(ok=False, error=str(exc))
        raise
    maps_store.log_load(ok=True, companies=saved[0], ratings=saved[1])
    logger.info("Оценки карт загружены: филиалов %d, оценок %d", *saved)
    return saved


def main() -> None:
    """Разовая загрузка руками: `python -m src.ratings.maps`."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    load_once()


if __name__ == "__main__":
    main()
