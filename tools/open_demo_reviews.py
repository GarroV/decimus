"""Оценки площадок открытого демо: агрегаторы доставки и карты — теми же дверями, что у сборщиков.

Блоки «Delivery app ratings» и «Map ratings» экрана «Рейтинги» и колонки карт таблицы
пиццерий в демо иначе пусты: сборщики (`src/bot/agg_loader.py`, `src/ratings/maps.py`)
на стенде не работают — бота там нет. Здесь оценки пишут `agg_store.save` и
`maps_store.save`, а связь с пиццерией — тем же полем `dodo_id`, что ставят привязки
продукта (`maps_store.save_links`), поэтому читают их те же запросы.

Точки и ключи выдуманные: без ссылок на настоящие страницы площадок (публичный демо-экран
не должен вести на чужие мёртвые адреса). Wolt — в Сербии и Грузии, Glovo — во всех
трёх странах; Google и Yandex — по каждой пиццерии. Оценка точки идёт за РС пиццерии
(`open_demo_ratings.RS_SCORES`): слабая по проверкам не получает пятёрку на витрине.
Снимки — раз в неделю назад на `WEEKS` и сегодняшний, даты от дня посева: срез
«текущий период» и сравнение с прошлым не пусты в любой день.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

import open_demo_ratings

from src.db import agg_store, maps_store
from src.db.agg_store import PointRow, RatingRow
from src.ratings import pointer

#: Сколько недель истории: квартала хватает на текущий и прошлый срез.
WEEKS = 14
#: Площадки доставки: (шкала, страны). Шкалы родные — Wolt из 10, Glovo в процентах.
AGGREGATORS = {
    "wolt": (10, ("RS", "GE")),
    "glovo": (100, ("RS", "GE", "AM")),
}
#: Центр страны — от него разносятся выдуманные точки; настоящие адреса не нужны.
CENTERS = {"RS": (44.80, 20.46), "GE": (41.72, 44.79), "AM": (40.18, 44.51)}
#: Пространство имён выдуманных ключей: одни и те же uuid от посева к посеву.
NAMESPACE = uuid.UUID("de000000-0000-4000-8000-000000000001")
NETWORK_NAME = "Demo Pizza"
#: Сколько отзывов у точки в начале окна и сколько прибавляется за неделю.
VOTES_BASE = 120
VOTES_PER_WEEK = 6


def _score_at(name: str, week: int) -> float:
    """РС точки на неделе окна: полумесячные баллы растягиваются на `WEEKS` недель."""
    series = open_demo_ratings.RS_SCORES[name]
    return series[min(len(series) - 1, week * len(series) // (WEEKS + 1))]


def _days(today: date) -> list[tuple[int, date]]:
    """(номер недели, дата снимка): от старого к сегодняшнему."""
    return [(w, today - timedelta(days=7 * (WEEKS - w))) for w in range(WEEKS + 1)]


def _wolt(rs: float, n: int) -> float:
    return round(min(9.8, 7.9 + (rs - 75) * 0.085 + (n % 3) * 0.05), 1)


def _glovo(rs: float, n: int) -> float:
    return float(min(98, round(80 + (rs - 75) * 0.75 + n % 3)))


def _delivery(
    units: Sequence[tuple[str, str]], ids: dict[str, str], today: date
) -> tuple[list[PointRow], list[RatingRow]]:
    points: list[PointRow] = []
    ratings: list[RatingRow] = []
    for n, (name, country) in enumerate(units, start=1):
        for aggregator, (scale, countries) in AGGREGATORS.items():
            if country not in countries:
                continue
            key = f"{aggregator}-demo-{n:03d}"
            lat, lng = CENTERS[country]
            points.append(
                PointRow(
                    aggregator=aggregator,
                    point_key=key,
                    country_code=country,
                    name=f"{NETWORK_NAME} {name}",
                    url=None,
                    lat=lat + n * 0.004,
                    lng=lng + n * 0.004,
                    dodo_id=ids[name],
                    dodo_name=name,
                    link_distance_m=20 + 15 * (n % 4),
                    extra={},
                )
            )
            for week, day in _days(today):
                rs = _score_at(name, week)
                score = _wolt(rs, n) if aggregator == "wolt" else _glovo(rs, n)
                ratings.append(
                    RatingRow(
                        aggregator=aggregator,
                        point_key=key,
                        on_date=day,
                        score=score,
                        scale=scale,
                        votes=VOTES_BASE + 35 * n + VOTES_PER_WEEK * week,
                        votes_exact=aggregator == "wolt",
                        is_open=True,
                    )
                )
    return points, ratings


def _maps(
    units: Sequence[tuple[str, str]], ids: dict[str, str], today: date
) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]], list[tuple[str, str, str, int]]]:
    """Филиалы, оценки (Google и Yandex) и связи с пиццериями."""
    companies: list[tuple[object, ...]] = []
    ratings: list[tuple[object, ...]] = []
    links: list[tuple[str, str, str, int]] = []
    network = str(uuid.uuid5(NAMESPACE, "network"))
    for n, (name, country) in enumerate(units, start=1):
        company = str(uuid.uuid5(NAMESPACE, f"company-{name}"))
        lat, lng = CENTERS[country]
        companies.append(
            (company, network, NETWORK_NAME, f"{NETWORK_NAME} {name}", country, name.split("-")[0],
             f"{10 + n} Main Street", lat + n * 0.004, lng + n * 0.004, 1, None)
        )  # fmt: skip
        links.append((company, ids[name], name, 15 + 10 * (n % 3)))
        for week, day in _days(today):
            rs = _score_at(name, week)
            google = round(min(4.9, 3.9 + (rs - 75) * 0.04 + (n % 3) * 0.03), 2)
            yandex = round(min(4.9, google - 0.1 + (n % 2) * 0.05), 2)
            for provider, avg, base in (
                (pointer.GOOGLE, google, 260),
                (pointer.YANDEX, yandex, 70),
            ):
                ratings.append((company, provider, day, avg, base + 18 * n + 3 * week))
    return companies, ratings, links


def seed(units: Sequence[tuple[str, str]], today: date) -> list[str]:
    """Записать оценки площадок доставки и карт. Возвращает строки отчёта."""
    ids = open_demo_ratings.unit_ids(units)
    points, rows = _delivery(units, ids, today)
    agg_store.save(points, rows)
    lines = []
    for aggregator in AGGREGATORS:
        mine = [p for p in points if p.aggregator == aggregator]
        agg_store.log_load(
            aggregator,
            ok=True,
            points=len(mine),
            ratings=sum(1 for r in rows if r.aggregator == aggregator and r.on_date == today),
        )
        lines.append(f"{aggregator}: {len(mine)} points")
    companies, ratings, links = _maps(units, ids, today)
    maps_store.save(companies, ratings)
    maps_store.save_links(links)
    maps_store.log_load(ok=True, companies=len(companies), ratings=len(companies) * 2)
    lines.append(f"maps: {len(companies)} companies, Google and Yandex")
    return lines
