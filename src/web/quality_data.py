"""Сборка данных «Качества» за месяц: из чтений — пиццерии и страны (docs/21-quality.md).

Здесь нет формул: ЛКО и ЭС считает ядро (`src/domain/quality.py`), оценку проверки приносит
движок. Модуль только складывает входы пиццерии за месяц из своих источников — рейтинги
(РКО, РС), проверки decimus, карты, агрегаторы, Dodo IS — и сворачивает пиццерии в страну
простым средним. Ничего не знает про экран: цифры наружу уходят `Decimal`, текст — дело
`quality_page`.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from src.db import agg_store, dodois_logins, dodois_metrics, maps_store, quality_read
from src.db.errors import DbError
from src.db.reach import Reach
from src.domain import quality as q
from src.ratings import pointer
from src.ratings.aggregators import collect

log = logging.getLogger(__name__)

#: Каналы продаж, как их показывает экран; всё нераспознанное — `other`.
SALES_CHANNELS = ("dine_in", "takeaway", "delivery")
#: Состояние данных Dodo IS у страны: есть; страна не подключена; подключена, но не собрано.
DODOIS_OK = "ok"
DODOIS_NOT_CONNECTED = "not_connected"
DODOIS_NOT_COLLECTED = "not_collected"

_APP_SITE = frozenset({"mobileapp", "website", "app", "web", "site"})


@dataclass(frozen=True)
class AggLine:
    """Агрегатор пиццерии за месяц: заказы и (если есть) оценка площадки."""

    name: str
    key: str | None
    orders: int
    score: Decimal | None
    scale: int | None

    @property
    def score5(self) -> Decimal | None:
        if self.score is None or not self.scale:
            return None
        return q.five_point(self.score, self.scale)


@dataclass(frozen=True)
class UnitQuality:
    dodo_id: str
    name: str
    country: str
    lko: q.Lko
    es: q.Es
    rko_checks: Decimal | None
    kr_parts: dodois_metrics.UnitKr | None
    maps: tuple[tuple[str, Decimal, int], ...]  # (карта, оценка, отзывов)
    orders: q.Orders
    revenue: dict[str, Decimal]
    aggs: tuple[AggLine, ...]
    #: Откуда РКО и РС: `dodois` (API), `sheet` (таблица контроля) или пусто.
    rating_source: str = ""

    @property
    def rko(self) -> Decimal | None:
        """Оценка РКО за месяц, сто баллов."""
        return None if self.lko.scores.rko is None else self.lko.scores.rko * q.RKO_DIVISOR


@dataclass(frozen=True)
class AggTotal:
    """Агрегатор страны за месяц: доля заказов, средняя оценка площадки по пиццериям."""

    name: str
    key: str | None
    orders: int
    share: Decimal | None
    score: Decimal | None
    scale: int | None
    score5: Decimal | None
    #: Заказы есть, а сбора оценок этой площадки у нас нет.
    no_collector: bool


@dataclass(frozen=True)
class KrTotal:
    dine_avg: Decimal | None
    dine_count: int
    delivery_avg: Decimal | None
    delivery_count: int


@dataclass(frozen=True)
class MapTotal:
    provider: str
    score: Decimal
    units: int
    reviews: int


@dataclass(frozen=True)
class CountryQuality:
    code: str
    units: tuple[UnitQuality, ...]
    lko: Decimal | None
    es: Decimal | None
    lko_units: int
    es_units: int
    scores: q.Scores
    weights: q.Weights
    es_audit: Decimal | None
    es_rs: Decimal | None
    orders: q.Orders
    revenue: dict[str, Decimal]
    currency: str | None
    aggs: tuple[AggTotal, ...]
    kr: KrTotal
    maps: tuple[MapTotal, ...]
    dodois: str
    rating_source: str = ""
    place_lko: int | None = None


def agg_key(name: str) -> str | None:
    """Ключ сборщика оценок для названия агрегатора из Dodo IS; нет сборщика — `None`."""
    flat = re.sub(r"[^a-z0-9]", "", name.lower())
    if len(flat) < 4:
        return None
    for module in (*collect.SEARCHERS, *collect.KNOWN, *collect.PAUSED):
        key = str(module.KEY)
        own = key.replace("_", "")
        if flat == own or own.startswith(flat) or flat.startswith(own):
            return key
    return None


def _group(source: str) -> str:
    low = source.lower()
    if "aggregator" in low:
        return "aggregators"
    return "app_site" if re.sub(r"[^a-z]", "", low) in _APP_SITE else "other"


def sales_channel(name: str) -> str:
    low = name.lower()
    if "dine" in low:
        return "dine_in"
    if "take" in low or "pickup" in low:
        return "takeaway"
    return "delivery" if "deliver" in low else "other"


def _mean(values: Iterable[Decimal]) -> Decimal | None:
    return q.mean(list(values))


def _checks_per_week(rows: Sequence[quality_read.PeriodScore]) -> Decimal | None:
    """Проверок РКО в неделю: по собираемости, а где её нет — по числу рейтинга."""
    counts = [r.collected if r.collected is not None else r.checkups for r in rows]
    return _mean(Decimal(n) for n in counts if n is not None)


def _kr(parts: dodois_metrics.UnitKr | None) -> Decimal | None:
    if parts is None:
        return None
    return q.combine_kr(
        parts.dine_in_avg, parts.dine_in_count, parts.delivery_avg, parts.delivery_count
    )


def _unit(
    dodo_id: str,
    name: str,
    country: str,
    *,
    scores: Sequence[quality_read.PeriodScore],
    audit: Decimal | None,
    maps: tuple[tuple[str, Decimal, int], ...],
    sales: Sequence[dodois_metrics.UnitSales],
    agg_orders: Sequence[dodois_metrics.UnitAggregatorOrders],
    kr: dodois_metrics.UnitKr | None,
    agg_scores: dict[str, tuple[Decimal, int]],
    periods: Sequence[dodois_metrics.UnitRatingPeriod] = (),
) -> UnitQuality:
    rko_rows = [r for r in scores if r.rating_type == "rko"]
    d_rko = [p for p in periods if p.kind == "rko"]
    d_rs = [p for p in periods if p.kind == "rs"]
    # Периоды из Dodo IS — первичны; нет их — таблица контроля (docs/21-quality.md).
    rko = _mean(p.rate for p in d_rko) if d_rko else _mean(r.score for r in rko_rows)
    rs = (
        _mean(p.rate for p in d_rs)
        if d_rs
        else _mean(r.score for r in scores if r.rating_type == "rs")
    )
    checks = _mean(Decimal(p.checkups) for p in d_rko if p.checkups is not None)
    if checks is None:
        checks = _checks_per_week(rko_rows)
    source = "dodois" if d_rko or d_rs else ("sheet" if scores else "")
    by_group: dict[str, int] = defaultdict(int)
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    for s in sales:
        by_group[_group(s.order_source)] += s.orders
        revenue[sales_channel(s.sales_channel)] += s.revenue
    lines: dict[str, AggLine] = {}
    for a in agg_orders:
        key = agg_key(a.aggregator)
        rated = agg_scores.get(key) if key else None
        prior = lines.get(a.aggregator)
        lines[a.aggregator] = AggLine(
            a.aggregator,
            key,
            a.orders + (prior.orders if prior else 0),
            rated[0] if rated else None,
            rated[1] if rated else None,
        )
    n_orders = by_group["aggregators"] or sum(a.orders for a in lines.values())
    orders = q.Orders(n_orders, by_group["app_site"], by_group["other"])
    agg5 = q.aggregator_score([(line.score5, line.orders) for line in lines.values()])
    result = q.lko(
        rko=rko,
        rko_checks_per_week=checks,
        kr=_kr(kr),
        maps=q.maps_score([(m[1], m[2]) for m in maps]),
        aggregators=agg5,
        orders=orders,
    )
    return UnitQuality(
        dodo_id,
        name,
        country,
        result,
        q.es(audit=audit, rs=rs),
        checks,
        kr,
        maps,
        orders,
        dict(revenue),
        tuple(sorted(lines.values(), key=lambda x: -x.orders)),
        source,
    )


def _agg_totals(units: Sequence[UnitQuality]) -> tuple[AggTotal, ...]:
    known = {str(m.KEY) for m in (*collect.SEARCHERS, *collect.KNOWN, *collect.PAUSED)}
    orders: dict[str, int] = defaultdict(int)
    keys: dict[str, str | None] = {}
    native: dict[str, list[Decimal]] = defaultdict(list)
    five: dict[str, list[Decimal]] = defaultdict(list)
    scales: dict[str, int] = {}
    for u in units:
        for line in u.aggs:
            orders[line.name] += line.orders
            keys[line.name] = line.key
            if line.score is not None and line.scale:
                native[line.name].append(line.score)
                scales[line.name] = line.scale
                five[line.name].append(q.five_point(line.score, line.scale))
    total = sum(orders.values())
    return tuple(
        AggTotal(
            name,
            keys[name],
            n,
            Decimal(n) / Decimal(total) if total else None,
            _mean(native[name]),
            scales.get(name),
            _mean(five[name]),
            keys[name] not in known,
        )
        for name, n in sorted(orders.items(), key=lambda kv: -kv[1])
    )


def _kr_total(units: Sequence[UnitQuality]) -> KrTotal:
    def side(pairs: list[tuple[Decimal, int]]) -> tuple[Decimal | None, int]:
        count = sum(n for _, n in pairs)
        if not count:
            return None, 0
        return sum((avg * n for avg, n in pairs), Decimal(0)) / count, count

    dine, delivery = [], []
    for u in units:
        p = u.kr_parts
        if p is None:
            continue
        if p.dine_in_avg is not None and p.dine_in_count > 0:
            dine.append((p.dine_in_avg, p.dine_in_count))
        if p.delivery_avg is not None and p.delivery_count > 0:
            delivery.append((p.delivery_avg, p.delivery_count))
    (da, dn), (va, vn) = side(dine), side(delivery)
    return KrTotal(da, dn, va, vn)


def _maps_total(units: Sequence[UnitQuality]) -> tuple[MapTotal, ...]:
    seen: dict[str, list[tuple[Decimal, int]]] = defaultdict(list)
    for u in units:
        for provider, score, count in u.maps:
            seen[provider].append((score, count))
    return tuple(
        MapTotal(p, q.maps_score(v) or Decimal(0), len(v), sum(c for _, c in v))
        for p, v in sorted(seen.items())
    )


def _source_of(units: Sequence[UnitQuality]) -> str:
    """Источник РКО и РС страны: `dodois`, `sheet`, `mixed` или пусто."""
    found = {u.rating_source for u in units if u.rating_source}
    if len(found) > 1:
        return "mixed"
    return next(iter(found), "")


def _country(
    code: str, units: Sequence[UnitQuality], currency: str | None, state: str
) -> CountryQuality:
    ranked = sorted(units, key=lambda u: (u.lko.score is None, -(u.lko.score or 0), u.name))
    with_lko = [u for u in ranked if u.lko.score is not None]

    def comp(pick: str) -> Decimal | None:
        return _mean(s for u in with_lko if (s := getattr(u.lko.scores, pick)) is not None)

    def weight(pick: str) -> Decimal:
        return _mean(getattr(u.lko.weights, pick) for u in with_lko) or Decimal(0)

    with_es = [u for u in ranked if u.es.score is not None]
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    for u in units:
        for ch, amount in u.revenue.items():
            revenue[ch] += amount
    return CountryQuality(
        code=code,
        units=tuple(ranked),
        lko=_mean(u.lko.score for u in with_lko if u.lko.score is not None),
        es=_mean(u.es.score for u in with_es if u.es.score is not None),
        lko_units=len(with_lko),
        es_units=len(with_es),
        scores=q.Scores(comp("rko"), comp("kr"), comp("maps"), comp("aggregators")),
        weights=q.Weights(weight("rko"), weight("kr"), weight("maps"), weight("aggregators")),
        es_audit=_mean(u.es.audit for u in with_es if u.es.audit is not None),
        es_rs=_mean(u.es.rs for u in with_es if u.es.rs is not None),
        orders=q.Orders(
            sum(u.orders.aggregators for u in units),
            sum(u.orders.app_site for u in units),
            sum(u.orders.other for u in units),
        ),
        revenue=dict(revenue),
        currency=currency,
        aggs=_agg_totals(units),
        kr=_kr_total(units),
        maps=_maps_total(units),
        dodois=state,
        rating_source=_source_of(units),
    )


def _connected() -> frozenset[str] | None:
    """Страны, где вход в Dodo IS есть; `None` — не прочитали (тогда «не подключена» не врём)."""
    try:
        return frozenset(login.country for login in dodois_logins.list_logins())
    except DbError:
        log.warning("Качество: входы Dodo IS не прочитались", exc_info=True)
        return None


def _month_end(month: date) -> date:
    return quality_read.next_month(month) - timedelta(days=1)


def _fresh_maps(provider: int, month: date) -> dict[str, tuple[float, int]]:
    """Оценки на карте, снятые внутри месяца (последняя на конец месяца, не старше его начала)."""
    return {
        code: (score, count)
        for code, (score, count, on) in maps_store.unit_scores_dated(
            provider, until=_month_end(month)
        ).items()
        if on >= month
    }


def load_month(
    reach: Reach, countries: Sequence[str], month: date, *, with_audit: bool = True
) -> dict[str, CountryQuality]:
    """«Качество» стран за месяц. Бросает `RatingsError`/`DbError`, если база не ответила.

    `with_audit=False` — проверки decimus не читаются вовсе (контроль их не видит, D420)."""
    until = _month_end(month)
    scores: dict[str, list[quality_read.PeriodScore]] = defaultdict(list)
    names: dict[str, tuple[str, str]] = {}
    for row in quality_read.period_scores(countries, month):
        scores[row.unit].append(row)
        names[row.unit] = (row.name, row.country)
    for reg in agg_store.units(countries):
        names.setdefault(reg.dodo_id, (reg.name, reg.country))
    audits = quality_read.audit_pcts(reach, countries, month) if with_audit else {}
    maps_by_provider = {
        "Google": _fresh_maps(pointer.GOOGLE, month),
        "Yandex": _fresh_maps(pointer.YANDEX, month),
    }
    agg_scores: dict[str, dict[str, tuple[Decimal, int]]] = defaultdict(dict)
    for rating in agg_store.latest(countries, until=until):
        if rating.on_date >= month:
            agg_scores[rating.dodo_id][rating.aggregator] = (
                Decimal(str(rating.score)),
                rating.scale,
            )
    connected = _connected()
    out: dict[str, CountryQuality] = {}
    for code in countries:
        out[code] = _load_country(
            code, month, scores, names, audits, maps_by_provider, agg_scores, connected
        )
    return out


def _load_country(
    code: str,
    month: date,
    scores: dict[str, list[quality_read.PeriodScore]],
    names: dict[str, tuple[str, str]],
    audits: dict[str, Decimal],
    maps_by_provider: dict[str, dict[str, tuple[float, int]]],
    agg_scores: dict[str, dict[str, tuple[Decimal, int]]],
    connected: frozenset[str] | None,
) -> CountryQuality:
    sales = dodois_metrics.unit_sales(code, month)
    agg_orders = dodois_metrics.unit_aggregator_orders(code, month)
    krs = {k.dodo_id: k for k in dodois_metrics.unit_kr(code, month)}
    rated = dodois_metrics.unit_rating_periods(code, month)
    in_country = {u for u, (_, c) in names.items() if c == code}
    ids = (
        in_country & (set(scores) | set(audits))
        | {s.dodo_id for s in sales}
        | {a.dodo_id for a in agg_orders}
        | set(krs)
        | {p.dodo_id for p in rated}
    )
    units = []
    for uid in sorted(ids):
        name, _ = names.get(uid, (uid[:8], code))
        maps = tuple(
            (provider, Decimal(str(found[uid][0])), found[uid][1])
            for provider, found in maps_by_provider.items()
            if uid in found
        )
        units.append(
            _unit(
                uid,
                name,
                code,
                scores=scores.get(uid, []),
                audit=audits.get(uid),
                maps=maps,
                sales=[s for s in sales if s.dodo_id == uid],
                agg_orders=[a for a in agg_orders if a.dodo_id == uid],
                kr=krs.get(uid),
                agg_scores=agg_scores.get(uid, {}),
                periods=[p for p in rated if p.dodo_id == uid],
            )
        )
    has_dodois = bool(sales or agg_orders or krs)
    if has_dodois:
        state = DODOIS_OK
    elif connected is not None and code not in connected:
        state = DODOIS_NOT_CONNECTED
    else:
        state = DODOIS_NOT_COLLECTED
    currency = next((s.currency for s in sales if s.currency), None)
    return _country(code, units, currency, state)


def rank(results: dict[str, CountryQuality]) -> dict[str, CountryQuality]:
    """Места стран по ЛКО (равные — одно место); страна без ЛКО места не получает."""
    places = q.places({c: r.lko for c, r in results.items()})
    return {c: replace(r, place_lko=places.get(c)) for c, r in results.items()}
