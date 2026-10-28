"""Экран «Качество»: ЛКО и ЭС по странам и пиццериям за месяц (docs/21-quality.md).

Вопрос экрана: «насколько хорош клиентский опыт и соблюдение стандартов — по сети, стране,
пиццерии, и из чего это складывается». Каркас — общий шаблон «выбор слева — рабочая область
справа» (`_pick_page.html`, D474, D655), как у «Стран»: слева страны с итогом и местом,
справа сводка сети или страна целиком — итог, разбивка, затем строки.

Состояние в адресе: `/quality?country=<код>&month=<ГГГГ-ММ>`. Период — один месяц на экран,
по умолчанию текущий (идёт, помечен). Доступ как у «Рейтингов»: УК видит страны IMF, партнёр — те,
что в охвате его пространства (`auth.current_reach`); чужая страна в адресе — 404.

Ничего не считает сам: формулы — `src/domain/quality.py`, сборка входов — `quality_data`.
Здесь только выбор месяца и страны и подписи.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from flask import Flask, abort, render_template, request, url_for

from src.db import dodois_metrics
from src.db import ratings_read as read
from src.db.errors import DbError, RatingsError
from src.domain import quality as q
from src.ratings.countries import country_names

from . import auth, guard, quality_data, ratings_freshness, ui_lang
from .config import Settings
from .geo_names import country_title as geo_title
from .quality_data import CountryQuality, UnitQuality
from .sections import section
from .texts import t

log = logging.getLogger(__name__)

DASH = "—"
#: Месяцев в выборе периода: дальше назад выбирать незачем.
MONTHS_SHOWN = 24


@dataclass(frozen=True)
class Delta:
    text: str
    #: `up`, `down`, `flat` или пусто (нет прошлого месяца).
    kind: str


def country_title(code: str, lang: str) -> str:
    title = geo_title(code, lang)
    if title and title != code:
        return title
    ru, en = country_names(code)
    return ru if lang == "ru" else en


def num(value: Decimal | None, places: int = 2) -> str:
    """Число с заданным числом знаков; нет данных — прочерк, а не ноль."""
    return DASH if value is None else f"{value:.{places}f}"


def lko_text(value: Decimal | None) -> str:
    return num(value, 2)


def es_text(value: Decimal | None) -> str:
    return num(value, 1)


def pct(value: Decimal | None) -> str:
    return DASH if value is None else f"{value * 100:.0f}%"


def share(part: int | Decimal, total: int | Decimal) -> str:
    return DASH if not total else f"{Decimal(part) / Decimal(total) * 100:.0f}%"


def money(value: Decimal, currency: str | None) -> str:
    text = f"{value:,.0f}".replace(",", " ")
    return f"{text} {currency}" if currency else text


def delta(now: Decimal | None, before: Decimal | None, places: int) -> Delta:
    """Движение к прошлому месяцу; нет одного из двух чисел — пусто."""
    if now is None or before is None:
        return Delta("", "")
    diff = now - before
    limit = Decimal(1) / (Decimal(10) ** places) / 2
    if abs(diff) < limit:
        return Delta(f"{0:.{places}f}", "flat")
    return Delta(f"{diff:+.{places}f}", "up" if diff > 0 else "down")


def default_month(today: date) -> date:
    """Текущий месяц: он ещё идёт, и экран помечает его «месяц идёт» (данные неполные)."""
    return today.replace(day=1)


def parse_month(raw: str, today: date) -> date:
    """Месяц из адреса `ГГГГ-ММ`; мусор и будущее — текущий месяц."""
    try:
        picked = datetime.strptime(raw.strip()[:7], "%Y-%m").date()
    except ValueError:
        return default_month(today)
    return picked if picked <= today.replace(day=1) else default_month(today)


def shift(month: date, step: int) -> date:
    index = month.year * 12 + month.month - 1 + step
    return date(index // 12, index % 12 + 1, 1)


def month_title(month: date, lang: str) -> str:
    return t(
        "quality.month.title", lang, month=t(f"registry.month.{month.month}", lang), year=month.year
    )


def month_label(month: date, lang: str, today: date) -> str:
    """Название месяца; текущий, ещё не закончившийся, помечен «месяц идёт»."""
    title = month_title(month, lang)
    if month < today.replace(day=1):
        return title
    return t("quality.month.in_progress", lang, title=title)


def _scope(reach_countries: tuple[str, ...] | None) -> tuple[str, ...]:
    imf = [row.code for row in read.countries() if row.is_imf]
    return tuple(c for c in imf if reach_countries is None or c in reach_countries)


def _available_months(today: date, scope: tuple[str, ...]) -> tuple[date, ...]:
    """Месяцы выбора: те, где у рейтингов или у Dodo IS что-то есть, плюс текущий."""
    found = set(read.period_months())
    for code in scope:
        found.update(dodois_metrics.months_with_data(code))
    found.add(default_month(today))
    limit = today.replace(day=1)
    return tuple(sorted((m for m in found if m <= limit), reverse=True))[:MONTHS_SHOWN]


def _unit_row(u: UnitQuality) -> dict[str, Any]:
    scores = u.lko.scores
    return {
        "name": u.name,
        "lko": lko_text(u.lko.score),
        "es": es_text(u.es.score),
        "es_status": u.es.status,
        "rko": num(u.rko, 1),
        "checks": num(u.rko_checks, 1),
        "rs": num(u.es.rs, 1),
        "audit": num(u.es.audit, 1),
        "kr": num(scores.kr),
        "maps": num(scores.maps),
        "aggs": num(scores.aggregators),
        "wsum": pct(u.lko.weight_sum) if u.lko.score is not None else DASH,
        "wsum_low": u.lko.score is not None and u.lko.sum_below_full,
    }


def _orders_rows(c: CountryQuality) -> list[dict[str, Any]]:
    def row(name: str, o: q.Orders) -> dict[str, Any]:
        return {
            "name": name,
            "orders": o.total,
            "n": share(o.aggregators, o.total),
            "o": share(o.app_site, o.total),
            "p": share(o.other, o.total),
        }

    return [row(u.name, u.orders) for u in c.units if u.orders.total]


def _revenue_rows(
    revenue: dict[str, Decimal], currency: str | None, lang: str
) -> list[dict[str, str]]:
    total = sum(revenue.values(), Decimal(0))
    order = (*quality_data.SALES_CHANNELS, "other")
    return [
        {
            "name": t(f"quality.channel.{ch}", lang),
            "amount": money(revenue[ch], currency),
            "share": share(revenue[ch], total),
        }
        for ch in order
        if ch in revenue and (revenue[ch] or ch != "other")
    ]


def _revenue_units(c: CountryQuality, lang: str) -> list[dict[str, Any]]:
    out = []
    for u in c.units:
        total = sum(u.revenue.values(), Decimal(0))
        if not total:
            continue
        out.append(
            {
                "name": u.name,
                "total": money(total, c.currency),
                "cells": [
                    share(u.revenue.get(ch, Decimal(0)), total)
                    for ch in quality_data.SALES_CHANNELS
                ],
            }
        )
    return out


def _agg_rows(c: CountryQuality) -> list[dict[str, Any]]:
    return [
        {
            "name": a.name,
            "orders": a.orders,
            "share": share(a.orders, sum(x.orders for x in c.aggs)),
            "score": DASH if a.score is None else f"{a.score:.2f} / {a.scale}",
            "score5": num(a.score5),
            "no_collector": a.no_collector,
            "no_score": not a.no_collector and a.score is None,
        }
        for a in c.aggs
    ]


def _country_view(
    c: CountryQuality, before: CountryQuality | None, lang: str, total: int
) -> dict[str, Any]:
    comps = (
        ("rko", c.scores.rko, c.weights.rko),
        ("kr", c.scores.kr, c.weights.kr),
        ("maps", c.scores.maps, c.weights.maps),
        ("aggregators", c.scores.aggregators, c.weights.aggregators),
    )
    wsum = c.weights.total
    return {
        "lko": lko_text(c.lko),
        "es": es_text(c.es),
        "lko_delta": delta(c.lko, before.lko if before else None, 2),
        "es_delta": delta(c.es, before.es if before else None, 1),
        "place": t("quality.place.of", lang, n=c.place_lko, total=total) if c.place_lko else DASH,
        "lko_units": c.lko_units,
        "es_units": c.es_units,
        "units_total": len(c.units),
        "comps": [
            {"name": t(f"quality.comp.{key}", lang), "score": num(score), "weight": pct(weight)}
            for key, score, weight in comps
        ],
        "wsum": pct(wsum),
        "wsum_low": c.lko is not None and wsum < 1,
        "es_audit": num(c.es_audit, 1),
        "es_rs": num(c.es_rs, 1),
        "es_share": pct(q.AUDIT_SHARE),
        "es_rs_share": pct(1 - q.AUDIT_SHARE),
        "es_missing": len(c.units) - c.es_units,
        "units": [_unit_row(u) for u in c.units],
        "orders_total": {
            "orders": c.orders.total,
            "n": share(c.orders.aggregators, c.orders.total),
            "o": share(c.orders.app_site, c.orders.total),
            "p": share(c.orders.other, c.orders.total),
        },
        "orders": _orders_rows(c),
        "revenue": _revenue_rows(c.revenue, c.currency, lang),
        "revenue_units": _revenue_units(c, lang),
        "aggs": _agg_rows(c),
        "kr": {
            "dine_avg": num(c.kr.dine_avg),
            "dine_count": c.kr.dine_count,
            "delivery_avg": num(c.kr.delivery_avg),
            "delivery_count": c.kr.delivery_count,
        },
        "maps": [
            {
                "name": t(f"quality.maps.{m.provider.lower()}", lang),
                "score": num(m.score),
                "units": m.units,
                "reviews": m.reviews,
            }
            for m in c.maps
        ],
        "dodois_note": _dodois_note(c.dodois, lang),
    }


def _dodois_note(state: str, lang: str) -> str:
    if state == quality_data.DODOIS_NOT_CONNECTED:
        return t("quality.dodois.not_connected", lang)
    if state == quality_data.DODOIS_NOT_COLLECTED:
        return t("quality.dodois.not_collected", lang)
    return ""


def _network_rows(
    now: dict[str, CountryQuality], before: dict[str, CountryQuality], lang: str, href: Any
) -> list[dict[str, Any]]:
    ordered = sorted(
        now.values(),
        key=lambda c: (
            c.place_lko is None,
            c.place_lko or 0,
            country_title(c.code, lang).casefold(),
        ),
    )
    return [
        {
            "place": c.place_lko or DASH,
            "title": country_title(c.code, lang),
            "href": href(c.code),
            "lko": lko_text(c.lko),
            "lko_delta": delta(c.lko, before[c.code].lko if c.code in before else None, 2),
            "es": es_text(c.es),
            "es_delta": delta(c.es, before[c.code].es if c.code in before else None, 1),
            "units": len(c.units),
        }
        for c in ordered
    ]


def _rail_line(c: CountryQuality, lang: str, show_audit: bool) -> str:
    if c.lko is None and (c.es is None or not show_audit):
        return t("quality.rail.none", lang)
    if not show_audit:
        return t("quality.rail.lko", lang, lko=lko_text(c.lko))
    return t("quality.rail.line", lang, lko=lko_text(c.lko), es=es_text(c.es))


def _freshness_rows(lang: str, show_audit: bool, source: str = "") -> tuple[str, ...]:
    try:
        states = dodois_metrics.load_states()
    except DbError:
        log.warning("Качество: состояние сбора Dodo IS не прочиталось", exc_info=True)
        states = []
    done = [s.last_ok_at for s in states if s.last_ok_at]
    dodois = (
        t("quality.tip.dodois", lang, at=max(done).strftime("%d.%m %H:%M"))
        if done
        else t("quality.tip.dodois_none", lang)
    )
    failed = sorted(s.country_code for s in states if s.last_error)
    errors = (t("quality.tip.dodois_error", lang, countries=", ".join(failed)),) if failed else ()
    return (
        t("quality.tip.unit", lang),
        t("quality.tip.lko", lang),
        *((t("quality.tip.es", lang),) if show_audit else ()),
        t("quality.tip.kr", lang),
        t("quality.tip.fresh", lang),
        dodois,
        *errors,
        *((t(f"quality.tip.source.{source}", lang),) if source else ()),
    )


def render(lang: str) -> str:
    """Экран «Качество»; страна и месяц — из адреса."""
    today = date.today()
    reach = auth.current_reach()
    code = (request.args.get("country") or "").strip().upper()[:2] or None
    month = parse_month(request.args.get("month", ""), today)
    base = section("quality").path
    keep_lang = request.args.get("lang", "")
    #: Контроль проверок decimus не видит (D420, `inspection.read`): без права ни чтения
    #: проверок, ни ЭС, ни колонки проверки — остаются ЛКО и рейтинги.
    show_audit = guard.may("inspection.read")

    def link(country: str | None, to_month: date | None = None) -> str:
        params: dict[str, Any] = {"month": f"{(to_month or month):%Y-%m}"}
        if country:
            params["country"] = country
        if keep_lang:
            params["lang"] = keep_lang
        return url_for("quality", **params)

    try:
        scope = _scope(reach.countries)
        if code and code not in scope:
            abort(404)
        months = _available_months(today, scope)
        now = quality_data.rank(quality_data.load_month(reach, scope, month, with_audit=show_audit))
        before = quality_data.load_month(reach, scope, shift(month, -1), with_audit=show_audit)
    except (DbError, RatingsError):
        log.exception("Качество: данные не прочитались")
        return render_template(
            "quality/index.html", failed=True, rail=(), view=None, section_path=base
        )
    ranked_total = sum(1 for c in now.values() if c.place_lko)
    rail = tuple(
        {
            "code": c.code,
            "title": country_title(c.code, lang),
            "meta": _rail_line(c, lang, show_audit),
            "count": c.place_lko if c.place_lko else "",
            "href": link(c.code),
            "on": c.code == code,
        }
        for c in sorted(
            now.values(),
            key=lambda c: (
                c.place_lko is None,
                c.place_lko or 0,
                country_title(c.code, lang).casefold(),
            ),
        )
    )
    options = tuple(
        {"href": link(code, m), "title": month_label(m, lang, today), "on": m == month}
        for m in months
    )
    prev_month, next_month = shift(month, -1), shift(month, 1)
    view: dict[str, Any] | None = None
    view_source = now[code].rating_source if code else ""
    network: list[dict[str, Any]] = []
    if code:
        view = _country_view(now[code], before.get(code), lang, ranked_total)
    else:
        network = _network_rows(now, before, lang, link)
    return render_template(
        "quality/index.html",
        failed=False,
        view=view,
        network=network,
        rail=rail,
        code=code,
        title=country_title(code, lang) if code else t("quality.network", lang),
        kicker=t("quality.kicker.country" if code else "quality.kicker.network", lang),
        network_href=link(None),
        month_options=options,
        month_title=month_label(month, lang, today),
        prev_href=link(code, prev_month),
        next_href=link(code, next_month) if next_month <= today.replace(day=1) else None,
        tip_rows=_freshness_rows(lang, show_audit, view_source),
        show_audit=show_audit,
        freshness=ratings_freshness.build(lang, {}),
        section_path=base,
    )


def install(app: Flask, conf: Settings) -> None:
    """Повесить экран «Качество». Заслон раздела — общий (`view.quality`)."""
    path = section("quality").path

    @app.get(path, endpoint="quality")
    def quality() -> str:
        return render(ui_lang.request_lang(conf.ui_lang))
