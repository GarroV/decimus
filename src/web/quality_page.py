"""Экран «Качество»: рабочая страница здоровья по странам и пиццериям за месяц.

Вопрос экрана: «как работают пиццерии сети — рейтинги, оценки клиентов, агрегаторы, каналы,
выручка, наша проверка — и что за месяц стало хуже». Есть итоговый рейтинг и веса компонентов
по методике аналитика (D719), мест нет (D677).
Каркас — общий шаблон «выбор слева — рабочая область справа» (`_pick_page.html`, D474, D655),
как у «Стран»: слева страны, справа таблица стран или страна целиком — строки пиццерий и блоки.

Состояние в адресе: `/quality?country=<код>&month=<ГГГГ-ММ>&sort=<столбец>&dir=desc`. Период —
один месяц на экран, по умолчанию текущий (идёт, помечен). Доступ как у «Рейтингов»: УК видит
страны IMF, партнёр — те, что в охвате его пространства (`auth.current_reach`); чужая страна в
адресе — 404.

Ничего не считает сам: средние и доли — `src/domain/quality.py`, сборка входов —
`quality_data`, ячейки — `quality_cells`. Здесь выбор месяца, страны, порядка и подписи.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
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
from .quality_cells import COLUMNS, DASH, cells, group_starts, money, num, pct, shown
from .quality_data import CountryHealth
from .sections import section
from .texts import t

log = logging.getLogger(__name__)

#: Месяцев в выборе периода: дальше назад выбирать незачем.
MONTHS_SHOWN = 24
SORT_KEYS = ("name", *(c.key for c in COLUMNS))


def country_title(code: str, lang: str) -> str:
    title = geo_title(code, lang)
    if title and title != code:
        return title
    ru, en = country_names(code)
    return ru if lang == "ru" else en


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


def sorted_by[T](
    items: list[T],
    key: str,
    descending: bool,
    name: Callable[[T], str],
    values: Callable[[T], dict[str, Decimal | None]],
) -> list[T]:
    """Порядок строк по столбцу; строки без значения — в конце при любом направлении."""
    if key == "name":
        return sorted(items, key=name, reverse=descending)
    known = [i for i in items if values(i).get(key) is not None]
    unknown = [i for i in items if values(i).get(key) is None]
    known.sort(key=lambda i: (values(i)[key] or Decimal(0), name(i)), reverse=descending)
    return known + sorted(unknown, key=name)


def _agg_rows(c: CountryHealth) -> list[dict[str, Any]]:
    total = sum(x.orders for x in c.aggs)
    return [
        {
            "name": a.name,
            "orders": a.orders,
            "share": pct(q.share(a.orders, total)),
            "score": DASH if a.score is None else f"{a.score:.2f} / {a.scale}",
            "score5": num(a.score5),
            "no_collector": a.no_collector,
            "no_score": not a.no_collector and a.score is None,
        }
        for a in c.aggs
    ]


def _revenue_rows(
    revenue: dict[str, Decimal], names: list[tuple[str, str]], currency: str | None
) -> list[dict[str, str]]:
    total = sum(revenue.values(), Decimal(0))
    return [
        {
            "name": name,
            "amount": money(revenue[key], currency),
            "share": pct(q.share(revenue[key], total)),
        }
        for key, name in names
        if key in revenue and (revenue[key] or key != "other")
    ]


def _source_name(source: str, lang: str) -> str:
    flat = "".join(ch for ch in source.lower() if ch.isalnum())
    key = f"quality.source.{flat}"
    shown = t(key, lang)
    return source if shown == key else shown


def _period_rows(c: CountryHealth, lang: str) -> list[dict[str, Any]]:
    rows = []
    for p in c.periods:
        if p.preliminary:
            status = t("quality.period.preliminary", lang, n=p.preliminary, total=p.units)
        elif p.published:
            status = t("quality.period.published", lang)
        else:
            status = DASH
        rows.append(
            {
                "kind": t(f"quality.period.{p.kind}", lang),
                "span": f"{p.start:%d.%m}–{p.end:%d.%m}",
                "units": p.units,
                "rate": num(p.rate, 1),
                "status": status,
                "preliminary": bool(p.preliminary),
            }
        )
    return rows


def _unit_rows(
    c: CountryHealth,
    before: CountryHealth | None,
    show_audit: bool,
    key: str,
    desc: bool,
    in_progress: bool,
) -> list[dict[str, Any]]:
    prior = {u.dodo_id: u for u in before.units} if before else {}
    ordered = sorted_by(list(c.units), key, desc, lambda u: u.name.casefold(), lambda u: u.values)
    return [
        {
            "name": u.name,
            "cells": cells(
                u.values,
                prior[u.dodo_id].values if u.dodo_id in prior else None,
                c.currency,
                show_audit=show_audit,
                in_progress=in_progress,
            ),
        }
        for u in ordered
    ]


def _pct_whole(value: Decimal) -> str:
    return f"{value * 100:.0f}%"


def _rko_tiers(lang: str) -> str:
    """Пороги веса РКО словами, из `q.RKO_TIERS` (от меньшего порога к большему)."""
    tiers = sorted(q.RKO_TIERS)
    parts = [t("quality.overall.tier.zero", lang, w=_pct_whole(q.ZERO))]
    for i, (floor, weight) in enumerate(tiers):
        if i + 1 < len(tiers):
            parts.append(
                t(
                    "quality.overall.tier.below",
                    lang,
                    n=f"{tiers[i + 1][0]:.0f}",
                    w=_pct_whole(weight),
                )
            )
        else:
            parts.append(
                t("quality.overall.tier.from", lang, n=f"{floor:.0f}", w=_pct_whole(weight))
            )
    return "; ".join(parts)


def _overall_rows(c: CountryHealth, lang: str) -> list[str]:
    """Блок «Как считается итог»: словами, числа порогов — из констант `quality`."""
    rows = [
        t("quality.overall.rko", lang, divisor=f"{q.RKO_DIVISOR:.0f}"),
        t("quality.overall.rko_weight", lang, tiers=_rko_tiers(lang)),
        t("quality.overall.maps", lang, w=_pct_whole(q.MAPS_WEIGHT)),
        t("quality.overall.rest", lang),
        t("quality.overall.sum", lang),
        t("quality.overall.missing", lang),
    ]
    if c.overall is not None:
        inc = (
            t("quality.overall.incomplete", lang, w=_pct_whole(c.overall.weights.total))
            if c.overall.incomplete
            else ""
        )
        rows.append(t("quality.overall.country", lang, inc=inc))
    else:
        rows.append(t("quality.overall.country_none", lang))
    rows.append(t("quality.overall.table", lang))
    return rows


def _dodois_note(state: str, lang: str) -> str:
    if state == quality_data.DODOIS_NOT_CONNECTED:
        return t("quality.dodois.not_connected", lang)
    if state == quality_data.DODOIS_NOT_COLLECTED:
        return t("quality.dodois.not_collected", lang)
    return ""


def _country_view(
    c: CountryHealth,
    before: CountryHealth | None,
    lang: str,
    show_audit: bool,
    key: str,
    desc: bool,
    in_progress: bool,
) -> dict[str, Any]:
    channels = [
        (ch, t(f"quality.channel.{ch}", lang)) for ch in (*quality_data.SALES_CHANNELS, "other")
    ]
    by_source = sorted(c.revenue_by_source, key=lambda s: -c.revenue_by_source[s])
    return {
        "total": cells(
            c.values,
            before.values if before else None,
            c.currency,
            show_audit=show_audit,
            in_progress=in_progress,
        ),
        "units": _unit_rows(c, before, show_audit, key, desc, in_progress),
        "units_total": len(c.units),
        "overall": _overall_rows(c, lang),
        "dodois_note": _dodois_note(c.dodois, lang),
        "aggs": _agg_rows(c),
        "revenue": _revenue_rows(c.revenue, channels, c.currency),
        "revenue_sources": _revenue_rows(
            c.revenue_by_source, [(s, _source_name(s, lang)) for s in by_source], c.currency
        ),
        "kr": {
            "dine_avg": num(c.kr.dine_avg),
            "dine_count": c.kr.dine_count,
            "delivery_avg": num(c.kr.delivery_avg),
            "delivery_count": c.kr.delivery_count,
        },
        "maps": [
            {"name": m.provider, "score": num(m.score), "units": m.units, "reviews": m.reviews}
            for m in c.maps
        ],
        "periods": _period_rows(c, lang),
    }


def _rail_line(c: CountryHealth, lang: str) -> str:
    rko, rs = c.values.get("rko"), c.values.get("rs")
    total = c.values.get("total")
    if rko is not None or rs is not None:
        line = t("quality.rail.line", lang, rko=num(rko, 1), rs=num(rs, 1))
        return t("quality.rail.total", lang, total=num(total, 2), line=line) if total else line
    if c.units:
        return t("quality.rail.units", lang, n=len(c.units))
    return t("quality.rail.none", lang)


def _has_values(c: CountryHealth) -> bool:
    return any(v is not None for v in c.values.values())


def _network_rows(
    now: dict[str, CountryHealth],
    before: dict[str, CountryHealth],
    lang: str,
    show_audit: bool,
    href: Callable[[str], str],
    key: str,
    desc: bool,
    in_progress: bool,
) -> list[dict[str, Any]]:
    ordered = sorted_by(
        [c for c in now.values() if _has_values(c)],
        key,
        desc,
        lambda c: country_title(c.code, lang).casefold(),
        lambda c: c.values,
    )
    return [
        {
            "title": country_title(c.code, lang),
            "href": href(c.code),
            "units": len(c.units),
            "cells": cells(
                c.values,
                before[c.code].values if c.code in before else None,
                c.currency,
                show_audit=show_audit,
                in_progress=in_progress,
                country=False,
            ),
        }
        for c in ordered
    ]


def _no_data_links(
    now: dict[str, CountryHealth], lang: str, href: Callable[[str], str]
) -> list[dict[str, str]]:
    """Страны без единого значения за месяц — одной строкой под таблицей."""
    empty = [c for c in now.values() if not _has_values(c)]
    empty.sort(key=lambda c: country_title(c.code, lang).casefold())
    return [{"title": country_title(c.code, lang), "href": href(c.code)} for c in empty]


CARRIED_SHOWN = 5


def _carried_rows(c: CountryHealth | None, lang: str) -> tuple[str, ...]:
    """Под «?»: у каких пиццерий месяц карты не принят, взято значение прошлого (D733)."""
    if c is None:
        return ()
    items = [
        f"{u.name} · {provider} ← {month_title(src, lang)}"
        for u in c.units
        for provider, src in u.maps_carried
    ]
    if not items:
        return ()
    more = len(items) - CARRIED_SHOWN
    listed = "; ".join(items[:CARRIED_SHOWN]) + (f" … +{more}" if more > 0 else "")
    return (t("quality.tip.maps_carried", lang, n=len(items), items=listed),)


def _freshness_rows(
    lang: str, show_audit: bool, source: str = "", carried: tuple[str, ...] = ()
) -> tuple[str, ...]:
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
        t("quality.tip.scores", lang),
        t("quality.tip.rko", lang),
        t("quality.tip.overall", lang),
        t("quality.tip.tone", lang),
        *((t("quality.tip.audit", lang),) if show_audit else ()),
        t("quality.tip.fresh", lang),
        t("quality.tip.maps", lang),
        *carried,
        dodois,
        *errors,
        *((t(f"quality.tip.source.{source}", lang),) if source else ()),
    )


def render(lang: str) -> str:
    """Экран «Качество»; страна, месяц и порядок — из адреса."""
    today = date.today()
    reach = auth.current_reach()
    code = (request.args.get("country") or "").strip().upper()[:2] or None
    month = parse_month(request.args.get("month", ""), today)
    sort_key = request.args.get("sort", "name")
    sort_key = sort_key if sort_key in SORT_KEYS else "name"
    desc = request.args.get("dir") == "desc"
    base = section("quality").path
    keep_lang = request.args.get("lang", "")
    #: Контроль проверок decimus не видит (D420, `inspection.read`): без права ни чтения
    #: проверок, ни столбца «Проверка».
    show_audit = guard.may("inspection.read")

    def link(
        country: str | None,
        to_month: date | None = None,
        order: tuple[str, bool] | None = None,
    ) -> str:
        params: dict[str, Any] = {"month": f"{(to_month or month):%Y-%m}"}
        if country:
            params["country"] = country
        picked, picked_desc = order if order else (sort_key, desc)
        if picked != "name":
            params["sort"], params["dir"] = picked, "desc" if picked_desc else "asc"
        if keep_lang:
            params["lang"] = keep_lang
        return url_for("quality", **params)

    try:
        scope = _scope(reach.countries)
        if code and code not in scope:
            abort(404)
        months = _available_months(today, scope)
        now = quality_data.load_month(reach, scope, month, with_audit=show_audit)
        before = quality_data.load_month(reach, scope, shift(month, -1), with_audit=show_audit)
    except (DbError, RatingsError):
        log.exception("Качество: данные не прочитались")
        return render_template(
            "quality/index.html", failed=True, rail=(), view=None, section_path=base
        )
    rail = tuple(
        {
            "code": c.code,
            "title": country_title(c.code, lang),
            "meta": _rail_line(c, lang),
            "href": link(c.code),
            "on": c.code == code,
        }
        for c in sorted(now.values(), key=lambda c: country_title(c.code, lang).casefold())
    )
    try:
        latest_data = dodois_metrics.latest_available_month((code,) if code else scope)
    except (DbError, RatingsError):
        log.warning("Качество: последний месяц данных не прочитался")
        latest_data = None
    options = tuple(
        {"href": link(code, m), "title": month_label(m, lang, today), "on": m == month}
        for m in months
    )
    prev_month, next_month = shift(month, -1), shift(month, 1)
    visible = shown(show_audit, country=bool(code))
    firsts = group_starts(visible)
    group_sizes = {g: sum(1 for c in visible if c.group == g) for g in {c.group for c in visible}}

    def column(key: str, group: str = "", first: bool = False) -> dict[str, Any]:
        return {
            "key": key,
            "label": t(
                "quality.col.unit" if key == "name" else f"quality.col.{key}",
                lang,
                w=_pct_whole(q.MAPS_WEIGHT),
            ),
            "href": link(code, order=(key, not (sort_key == key and desc))),
            "on": sort_key == key,
            "desc": sort_key == key and desc,
            "group": group,
            "group_label": t(f"quality.group.{group}", lang) if group and first else "",
            #: Памятка под «?» у заголовка группы «Карты» (по пиццерии и по стране).
            "group_tip": (t("quality.tip.maps_head", lang),) if group == "maps" and first else (),
            "group_span": group_sizes.get(group, 1),
            "edge": first,
        }

    columns = (
        column("name"),
        *(column(c.key, c.group, f) for c, f in zip(visible, firsts, strict=True)),
    )
    in_progress = month >= today.replace(day=1)
    view: dict[str, Any] | None = None
    view_source = now[code].rating_source if code else ""
    network: list[dict[str, Any]] = []
    if code:
        view = _country_view(
            now[code], before.get(code), lang, show_audit, sort_key, desc, in_progress
        )
    else:
        network = _network_rows(now, before, lang, show_audit, link, sort_key, desc, in_progress)
    return render_template(
        "quality/index.html",
        failed=False,
        view=view,
        network=network,
        no_data=_no_data_links(now, lang, link) if not code else [],
        no_data_title=month_title(month, lang).lower()
        if lang == "ru"
        else month_title(month, lang),
        columns=columns,
        rail=rail,
        code=code,
        title=country_title(code, lang) if code else t("quality.network", lang),
        kicker=t("quality.kicker.country" if code else "quality.kicker.network", lang),
        network_href=link(None),
        month_options=options,
        latest_data_href=link(code, latest_data) if latest_data and latest_data < month else None,
        latest_data_title=month_title(latest_data, lang) if latest_data else None,
        month_title=month_label(month, lang, today),
        prev_href=link(code, prev_month),
        next_href=link(code, next_month) if next_month <= today.replace(day=1) else None,
        tip_rows=_freshness_rows(
            lang, show_audit, view_source, _carried_rows(now.get(code) if code else None, lang)
        ),
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
