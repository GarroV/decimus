"""Сбор оценок во всех агрегаторах: обход, привязка к пиццериям, страж, запись.

**Два вида сборщиков.** *Поиск у координат* (`SEARCHERS`): от координат каждой
работающей пиццерии страны агрегатора — так сами ловятся новые пиццерии и
переезды страниц. *Известная точка* (`KNOWN`): поиска с сервера нет, точка
берётся из справочника `agg.points`, оценка снимается по её id.

**Привязка** точки к пиццерии — ближайшая не дальше `MAX_LINK_M`, одна точка —
одной пиццерии и наоборот: пары разбираются от самой близкой. Точка Додо без
пиццерии рядом тоже записывается (без кода пиццерии) — так видно, что на
витрине есть то, чего нет в публичном API, — но в оценки не входит.

**Реестр пиццерий.** Каждый сбор читает публичный API Dodo по всем странам IMF и
кладёт пиццерии в `agg.units` (D424): новая появляется сама, по реестру строится
экран «Пиццерии на площадках». Сбой записи реестра сбор не останавливает. Glovo
после обновления известных точек сам ищет точки новым пиццериям (`glovo_link`).

**Страж.** Агрегатор вернул 0 точек, а прошлый удачный сбор принёс больше, или
не ответил ни на один запрос — это сбой (`failed` в журнале), а не «Додо
пропал»: снимок дня не пишется, на странице остаются прошлые оценки с датой.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, MutableMapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from types import ModuleType

from src.db import agg_store
from src.db.agg_store import PointRow, RatingRow
from src.db.errors import RatingsError
from src.ratings import maps_link
from src.ratings.maps_link import DodoUnit

from . import (
    base,
    bolt,
    chowdeck,
    glovo,
    glovo_link,
    migros,
    pyszne,
    trendyol,
    wolt,
    yandex_eda,
    yemeksepeti,
)
from .base import AggregatorError, Found

logger = logging.getLogger(__name__)

SEARCHERS: tuple[ModuleType, ...] = (wolt, bolt, yemeksepeti, trendyol, pyszne)
#: Сборщики на паузе: модуль цел, но бот к агрегатору не ходит. Яндекс Еда —
#: 429, затем 401 на поиске (#670); владелец 11.10.2026: «у яндекса в целом беда
#: сейчас, так что давай пока его пропустим» (D397). Вернуть — перенести в SEARCHERS.
PAUSED: tuple[ModuleType, ...] = (yandex_eda,)
KNOWN: tuple[ModuleType, ...] = (glovo, chowdeck, migros)
MAX_LINK_M = 400


@dataclass(frozen=True)
class Outcome:
    aggregator: str
    ok: bool
    points: int
    ratings: int
    error: str | None


def assign(
    candidates: Sequence[tuple[str, str, float]],
) -> dict[str, tuple[str, int]]:
    """(точка, пиццерия, метры) → точка: (пиццерия, метры). Ближайшие пары
    первыми; точка и пиццерия берутся по разу; дальше `MAX_LINK_M` — не пара."""
    taken_points: dict[str, tuple[str, int]] = {}
    taken_units: set[str] = set()
    for point, unit, metres in sorted(candidates, key=lambda c: c[2]):
        if metres > MAX_LINK_M or point in taken_points or unit in taken_units:
            continue
        taken_points[point] = (unit, round(metres))
        taken_units.add(unit)
    return taken_points


def verdict(points: int, errors: int, attempts: int, last_ok_points: int) -> str | None:
    """Почему сбор считать сбоем, или None — удался."""
    if attempts and errors == attempts:
        return f"не ответил ни на один из {attempts} запросов"
    if points == 0 and last_ok_points > 0:
        return f"пустой ответ: ни одной точки Додо, в прошлый раз было {last_ok_points}"
    return None


def _rating(aggregator: str, found: Found, today: date) -> RatingRow | None:
    if found.score is None or not 0 <= found.score <= found.scale:
        return None
    return RatingRow(
        aggregator,
        found.point_key,
        today,
        found.score,
        found.scale,
        found.votes,
        found.votes_exact,
        found.is_open,
    )


def _search_one(
    module: ModuleType, units: Sequence[DodoUnit], today: date
) -> tuple[list[PointRow], list[RatingRow], int, int, str | None]:
    """Обойти пиццерии агрегатора: точки, оценки, ошибок, попыток, первая ошибка."""
    http = base.Http(module.GAP_SEC, getattr(module, "HEADERS", None))
    cache: MutableMapping[str, object] = {}
    mine = [u for u in units if u.working and u.country in module.COUNTRIES]
    seen: dict[str, tuple[Found, str]] = {}
    candidates: list[tuple[str, str, float]] = []
    errors, first_error = 0, None
    for unit in mine:
        try:
            found = module.search(http, unit.lat, unit.lng, unit.country, cache)
        except AggregatorError as exc:
            errors += 1
            first_error = first_error or f"{unit.name}: {exc}"
            logger.warning("%s: %s не прочиталась (%s)", module.KEY, unit.name, exc)
            continue
        for point in found:
            seen.setdefault(point.point_key, (point, unit.country))
            if point.lat is not None and point.lng is not None:
                far = maps_link.distance_m(unit.lat, unit.lng, point.lat, point.lng)
                candidates.append((point.point_key, unit.dodo_id, far))
    links = assign(candidates)
    names = {u.dodo_id: u.name for u in mine}
    points, ratings = [], []
    for key, (point, country) in seen.items():
        link = links.get(key)
        dodo: str | None = link[0] if link else None
        metres: int | None = link[1] if link else None
        points.append(
            PointRow(
                module.KEY,
                key,
                country,
                point.name,
                point.url,
                point.lat,
                point.lng,
                dodo,
                names.get(dodo) if dodo else None,
                metres,
                dict(point.extra),
            )
        )
        rating = _rating(module.KEY, point, today)
        if rating:
            ratings.append(rating)
    return points, ratings, errors, len(mine), first_error


def _known_one(
    module: ModuleType, units: Sequence[DodoUnit], today: date
) -> tuple[list[PointRow], list[RatingRow], int, int, str | None]:
    """Снять оценки точек агрегатора из справочника."""
    http = base.Http(module.GAP_SEC)
    known = agg_store.known_points(module.KEY)
    points, ratings = [], []
    errors, first_error = 0, None
    for row in known:
        try:
            found = module.refresh(http, row)
        except AggregatorError as exc:
            errors += 1
            first_error = first_error or f"{row.dodo_name or row.point_key}: {exc}"
            logger.warning("%s: точка %s не прочиталась (%s)", module.KEY, row.point_key, exc)
            continue
        points.append(
            PointRow(
                row.aggregator,
                row.point_key,
                row.country_code,
                found.name or row.name,
                row.url,
                found.lat or row.lat,
                found.lng or row.lng,
                row.dodo_id,
                row.dodo_name,
                row.link_distance_m,
                dict(found.extra),
            )
        )
        rating = _rating(module.KEY, found, today)
        if rating:
            ratings.append(rating)
    if module is glovo:
        new_points, new_ratings = glovo_link.discover(
            base.Http(module.GAP_SEC),
            [u for u in units if u.working],
            known,
            agg_store.point_keys(module.KEY),
            today,
        )
        points.extend(new_points)
        ratings.extend(new_ratings)
    return points, ratings, errors, len(known), first_error


def run_one(module: ModuleType, units: Sequence[DodoUnit], today: date) -> Outcome:
    """Один агрегатор: собрать, проверить стражем, записать снимок и журнал."""
    try:
        if module in KNOWN:
            points, ratings, errors, attempts, first = _known_one(module, units, today)
        else:
            points, ratings, errors, attempts, first = _search_one(module, units, today)
        failure = verdict(len(points), errors, attempts, agg_store.last_ok_points(module.KEY))
        if failure:
            outcome = Outcome(
                module.KEY, False, len(points), 0, f"{failure}; {first or ''}".strip("; ")
            )
        else:
            saved = agg_store.save(points, ratings)
            note = f"ошибок {errors} из {attempts}: {first}" if errors else None
            outcome = Outcome(module.KEY, True, saved[0], saved[1], note)
    except Exception as exc:  # сбой одного агрегатора не останавливает остальные
        logger.exception("%s: сбор упал", module.KEY)
        outcome = Outcome(module.KEY, False, 0, 0, f"{exc.__class__.__name__}: {exc}")
    agg_store.log_load(
        outcome.aggregator,
        ok=outcome.ok,
        points=outcome.points,
        ratings=outcome.ratings,
        error=outcome.error,
    )
    logger.info(
        "Агрегатор %s: %s, точек %d, оценок %d%s",
        outcome.aggregator,
        "ок" if outcome.ok else "СБОЙ",
        outcome.points,
        outcome.ratings,
        f" — {outcome.error}" if outcome.error else "",
    )
    return outcome


def countries(modules: Sequence[ModuleType] = SEARCHERS) -> frozenset[str]:
    return frozenset().union(*(m.COUNTRIES for m in modules if m in SEARCHERS + PAUSED))


def _save_registry(units: Sequence[DodoUnit], today: date) -> None:
    """Реестр пиццерий в базу. Отказ — в журнал: сбор оценок из-за него не встаёт."""
    try:
        agg_store.save_units(units, today)
    except RatingsError:
        logger.exception("Реестр пиццерий не записался — сбор идёт дальше")


def _registry_countries(searching: Sequence[ModuleType]) -> frozenset[str]:
    """Страны для чтения публичного API: все IMF плюс страны сборщиков. База не
    ответила — только страны сборщиков, с записью в журнал."""
    try:
        imf = frozenset(agg_store.imf_countries())
    except RatingsError:
        logger.exception("Страны IMF не прочитались — берём страны сборщиков")
        imf = frozenset()
    return imf | countries(searching)


def run_all(
    today: date,
    *,
    only: Sequence[str] = (),
    fetch_units: Callable[[frozenset[str]], Sequence[DodoUnit]] = maps_link.fetch_units,
) -> tuple[Outcome, ...]:
    """Все агрегаторы (или перечисленные) параллельно — по потоку на агрегатор.

    Нагрузка на каждую витрину та же, что и подряд: у агрегатора свой `Http` со
    своей паузой, а разные агрегаторы — разные сайты. Подряд сбор длится сумму
    всех агрегаторов (на проде 11.10.2026 один Wolt — 9 минут), параллельно —
    самый долгий из них."""
    # Сборщик на паузе бот не зовёт, но руками (`run yandex_eda`) он работает —
    # так проверяют, вернулся ли агрегатор.
    every = SEARCHERS + KNOWN + PAUSED
    modules = [m for m in every if m.KEY in only] if only else list(SEARCHERS + KNOWN)
    if not modules:
        return ()
    searching = [m for m in modules if m in SEARCHERS + PAUSED]
    units = fetch_units(_registry_countries(searching))
    _save_registry(units, today)
    with ThreadPoolExecutor(max_workers=len(modules), thread_name_prefix="agg") as pool:
        return tuple(pool.map(lambda m: run_one(m, units, today), modules))
