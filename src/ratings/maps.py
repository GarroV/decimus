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
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from src.db import maps_store
from src.db.maps_store import LatestRating

from . import pointer

logger = logging.getLogger(__name__)

KEY_ENV = "POINTER_API_KEY"
SHOWN_PROVIDERS = (pointer.GOOGLE, pointer.YANDEX)
HISTORY_DAYS = pointer.HISTORY_WINDOW_DAYS


@dataclass(frozen=True)
class MapScore:
    avg: float | None  # None — отзывов на этой карте нет
    reviews: int
    branches: int  # филиалов страны на этой карте, с отзывами или без
    delta: float | None = None  # к концу прошлого периода; None — сравнивать не с чем


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


def with_delta(
    current: Sequence[CountryMaps], before: Sequence[CountryMaps]
) -> tuple[CountryMaps, ...]:
    """Текущая сводка с изменением к прошлой — страна к стране, карта к карте."""
    was = {row.country: row for row in before}
    result = []
    for row in current:
        old = was.get(row.country)
        scores = {}
        for provider, score in row.scores.items():
            prev = old.scores.get(provider) if old else None
            delta = (
                round(score.avg - prev.avg, 2)
                if score.avg is not None and prev is not None and prev.avg is not None
                else None
            )
            scores[provider] = MapScore(score.avg, score.reviews, score.branches, delta)
        result.append(CountryMaps(row.country, scores, row.as_of))
    return tuple(result)


def _key_fetch() -> pointer.Fetch:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise pointer.PointerError(f"{KEY_ENV} не задан — загрузка оценок карт выключена")
    return pointer.http_fetch(key)


def backfill(months: int, *, today: date, fetch: pointer.Fetch | None = None) -> int:
    """Дозагрузить историю оценок всех филиалов на `months` месяцев назад.

    Окна по 30 дней (лимит Pointer — 31). Окно, где у филиала уже есть почти все
    дни, пропускается: прерванная дозагрузка продолжается с места, а не с начала.
    Возвращает, сколько оценок легло.
    """
    fetch = fetch or _key_fetch()
    uuids = maps_store.company_uuids()
    windows = [
        (
            today - timedelta(days=HISTORY_DAYS * (i + 1) - 1),
            today - timedelta(days=HISTORY_DAYS * i),
        )
        for i in range(max(1, round(months * 30 / HISTORY_DAYS)))
    ]
    saved = 0
    for n, uuid in enumerate(uuids, 1):
        for start, end in windows:
            if maps_store.covered_days(uuid, start, end) >= HISTORY_DAYS - 2:
                continue
            ratings = pointer.history(fetch, uuid, start, end)
            rows = [
                (uuid, r.provider_id, r.on_date, r.avg_rating, r.ratings_count) for r in ratings
            ]
            saved += maps_store.save([], rows)[1]
        if n % 20 == 0:
            logger.info("История карт: филиалов %d из %d, оценок легло %d", n, len(uuids), saved)
    maps_store.log_load(ok=True, ratings=saved, error=f"history {months} months")
    logger.info("История карт загружена: оценок %d", saved)
    return saved


def load_once(fetch: pointer.Fetch | None = None) -> tuple[int, int]:
    """Забрать сети и филиалы с оценками и записать снимок. След — в журнале загрузок."""
    fetch = fetch or _key_fetch()
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
    """Руками: `python -m src.ratings.maps` — снимок сегодня;
    `python -m src.ratings.maps history 12` — история на 12 месяцев назад."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = sys.argv[1:]
    if args[:1] == ["history"]:
        backfill(int(args[1]) if len(args) > 1 else 12, today=date.today())
    else:
        load_once()


if __name__ == "__main__":
    main()
