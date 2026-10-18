"""Сборка экрана «Пиццерии» (D467, D474, D504, D527): колонка выбора слева, рабочая область справа.

Каркас — общий шаблон «выбор слева — рабочая область справа»
(`templates/_pick_page.html`, `docs/12-web-admin.md`). Слева поиск, отбор
«Девелопер» и страны списком (код, средняя за период, пиццерий); под выбранной
страной — её пиццерии (D504). Справа — шапка с периодом, плитки ключевых цифр и
«Где болит»; сведения и история пиццерии — в панели справа (D527: строка списка
открывается на этом же экране, а не отдельной страницей).
Состояние живёт в адресе: период `from` / `to`,
`unit=<ключ>` (панель пиццерии), `dev=<девелопер>` (отбор стран), `q=<поиск>` —
ссылку на открытое отправляют коллеге, и он видит ровно это; без скриптов всё —
ссылки и обычная форма поиска.

Ничего не считает: цифры — снимок «Обзора» с отбором по стране
(`country.py`), рейтинги — `home_ratings_block` теми же функциями, что у
«Рейтингов» и «Главной», строки таблицы — `country_units.py`. Предписания и
экшн-планы с экрана ушли: их счётчики в шапке ведут в «Действия» с отбором по
стране, и ничего не теряется.

Кто видит экран, решает матрица (`view.country`) и охват вошедшего
(`auth.current_reach`). Партнёр (D508) попадает сюда с «Главной» и видит ровно
то же, но только свои страны: чужая страна в адресе — тот же 404, что у
несуществующей; выбора девелопера у него нет, а выбор страны — только если
стран в пространстве больше одной.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from flask import abort, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db.models import InspectionRow
from src.domain.tenants import HQ_TENANT

from . import (
    action_plans,
    auth,
    country_summary,
    country_units,
    home_ratings_block,
    prescriptions,
    registry_period,
    registry_view,
    view,
)
from . import country as country_data
from . import overview as overview_data
from .geo_names import city_title, country_title
from .sections import section
from .texts import t
from .unit_add import can_add_here

log = logging.getLogger(__name__)

#: Сколько названий партнёров перечислять в шапке; остальные — числом.
PARTNERS_SHOWN = 2

#: Длина кода девелопера из адреса — как у поля справочника (`ratings.countries`).
DEVELOPER_MAX = 120

#: Длина поискового запроса по колонке (страны и пиццерии).
SEARCH_MAX = 60


def _url(endpoint: str, **params: Any) -> str:
    return url_for(endpoint, **{k: v for k, v in params.items() if v})


def _country_plans(код: str) -> dict[str, Any]:
    """Счётчик экшн-планов шапки: запросы, их состояние и куда действовать."""
    открытые, принятые, известны = action_plans.country_plans(код)
    уК = action_plans.is_hq()
    return {
        "plans": открытые.rows + принятые.rows,
        "plans_known": известны,
        "plans_act_path": section("actions" if уК else "plans").path,
        "plans_act_country": уК,
    }


def _partners(rows: tuple[country_units.UnitRow, ...]) -> tuple[str, ...]:
    """Партнёры страны по действующим пиццериям, по алфавиту, без повторов."""
    return tuple(sorted({r.partner for r in rows if r.partner and not r.is_closed}))


def _ratings(code: str, period: registry_period.Period, today: date) -> tuple[Any, bool]:
    """Колонка рейтингов страны для плиток; нет колонки — `None`. Второе — сбой чтения."""
    block = home_ratings_block.load(
        scope=auth.current_reach().countries, country=code, period=period, today=today
    )
    column = next((c for c in block.columns if c.key == code), None)
    return column, block.failed


def render(
    *,
    code: str | None,
    lang: str,
    limit: int,
    item_titles: dict[str, str],
    pick: Callable[..., Any],
) -> str | Response:
    """Экран страны `code`; `None` — вход без страны: первая в колонке или сводка девелопера."""
    today = date.today()
    reach = auth.current_reach()
    уК = auth.current_tenant() == HQ_TENANT
    code = country_data.normalize_code(code) if code is not None else None
    # Граница партнёра (D508): страна вне его охвата — 404, как у несуществующей.
    # Дальше по экрану охват работает в запросах, но справочник свода пиццерий
    # (`unit_profiles.by_country`) читается по одному коду страны, и без этой
    # проверки партнёр прочитал бы чужую страну подстановкой кода в адрес.
    if code is not None and reach.countries is not None and code not in reach.countries:
        abort(404)
    страны = country_data.countries(reach=reach)
    # Девелопер — понятие УК (D508): партнёру ни списка, ни отбора по нему.
    devs, dev_of, devs_failed = (
        country_summary.developers_of([c for c, _n in страны]) if уК else ({}, {}, False)
    )
    dev = request.args.get("dev", "").strip()[:DEVELOPER_MAX]
    if dev not in devs:
        dev = ""
    query = request.args.get("q", "").strip()[:SEARCH_MAX]
    в_колонке = tuple((c, n) for c, n in страны if not dev or c in devs[dev])
    combined = code is None and bool(dev)
    if code is None and not combined:
        if not в_колонке:
            return render_template(
                "country/index.html",
                view=None,
                combined=False,
                rail=(),
                group_row=None,
                dev_pick=None,
                query=query,
                search_hidden={},
                single_country=False,
                pick_open=False,
            )
        code = в_колонке[0][0]
    period = registry_period.read(request.args, today=today)
    before = registry_period.shift(period, -1)

    def select(**changes: str) -> str:
        """Адрес этого же экрана с изменённым срезом; пустое и умолчания выпадают."""
        params = {
            **period.params(),
            "dev": dev,
            "q": query,
            "unit": request.args.get("unit", "").strip()[:80] if not combined else "",
            "lang": lang,
            **changes,
        }
        if combined:
            return _url("country_index", **params)
        return _url("country", code=code or "-", **params)

    def to_country(target: str) -> str:
        """Строка колонки: тот же период, девелопер и поиск, но без раскрытой пиццерии."""
        return _url("country", code=target, **period.params(), dev=dev, q=query, lang=lang)

    stats = country_data.rail_stats(reach=reach, dates=_dates(period))
    rail = _rail(в_колонке, query, lang, stats, to_country, current=None if combined else code)
    dev_pick = (
        pick(
            label=t("country.dev.label", lang),
            empty_title=t("country.dev.all", lang),
            current=dev,
            values=tuple((name, len(members)) for name, members in devs.items()),
            href=lambda значение: (
                _url("country_index", dev=значение, q=query, lang=lang, **period.params())
                if значение or combined
                else select(dev="")
            ),
            title=str,
        )
        if devs
        else None
    )
    common: dict[str, Any] = {
        "choices": страны,
        "rail": rail,
        "dev": dev,
        "dev_pick": dev_pick,
        "devs_failed": devs_failed,
        "query": query,
        "search_hidden": {
            k: v for k, v in (*period.params().items(), ("dev", dev), ("lang", lang)) if v
        },
        "group_row": (
            {
                "title": dev,
                "units": sum(n for _c, n in в_колонке),
                "count": len(devs[dev]),
                "href": _url("country_index", dev=dev, q=query, lang=lang, **period.params()),
                "on": combined,
            }
            if dev
            else None
        ),
        "period": period,
        "period_title": registry_view.period_title(period, lang),
        "period_prev": registry_view.period_link(period, -1, select),
        "period_next": registry_view.period_link(period, 1, select),
        "period_quick": registry_view.period_quick(period, today, lang, select),
        "period_hidden": {k: v for k, v in (("dev", dev), ("q", query), ("lang", lang)) if v},
        "select_url": select,
        "all_time_url": select(**{"from": "", "to": "", "period": registry_period.ALL}),
        "item_titles": item_titles,
        "grade_tone": view.grade_tone,
        "level_tone": view.level_tone,
        "registry_path": section("registry").path,
        "combined": combined,
        "limit": limit,
        "is_hq": уК,
        # Партнёр с одной страной выбора страны не видит (D508).
        "single_country": not уК and len(страны) <= 1,
    }
    if combined:
        return render_template(
            "country/index.html",
            **common,
            **_combined(devs[dev], to_country, period, before, limit),
        )
    return render_template(
        "country/index.html",
        **common,
        **_one_country(
            code or "",
            dev_of.get(code or "", ""),
            select,
            query,
            period,
            before,
            limit,
            today,
            lang,
        ),
    )


def _rail(
    countries: tuple[tuple[str, int], ...],
    query: str,
    lang: str,
    stats: dict[str, tuple[float | None, int]],
    to_country: Callable[[str], str],
    *,
    current: str | None,
) -> tuple[dict[str, Any], ...]:
    """Строки колонки стран: код, название, пиццерий, средняя и проверок за период.

    Поиск — по названию на языке экрана и по коду, без учёта регистра; выбранная
    страна остаётся в колонке при любом запросе — под ней её пиццерии.
    """
    needle = query.casefold()
    rows = []
    for code, units in countries:
        title = country_title(code, lang) or code
        if (
            needle
            and code != current
            and needle not in title.casefold()
            and needle not in code.casefold()
        ):
            continue
        average, inspections = stats.get(code, (None, 0))
        rows.append(
            {
                "code": code,
                "title": title,
                "units": units,
                "average": average,
                "inspections": inspections,
                "href": to_country(code),
                "on": code == current,
            }
        )
    return tuple(rows)


def _unit_matches(row: country_units.UnitRow, needle: str, lang: str) -> bool:
    """Поиск по колонке: название пиццерии или её город."""
    return needle in row.name.casefold() or needle in (city_title(row.city, lang) or "").casefold()


def _dates(period: registry_period.Period) -> tuple[date | None, date | None]:
    return (period.start, period.end)


def _combined(
    codes: tuple[str, ...],
    to_country: Callable[[str], str],
    period: registry_period.Period,
    before: registry_period.Period | None,
    limit: int,
) -> dict[str, Any]:
    """Общая сводка стран девелопера и строка на каждую."""
    reach = auth.current_reach()
    views = [
        country_data.load(
            reach=reach,
            limit=limit,
            code=c,
            selection=overview_data.Selection(),
            dates=_dates(period),
            dates_before=_dates(before) if before else None,
        )
        for c in codes
    ]
    snapshots = [v.snapshot for v in views]
    return {
        "view": None,
        "summary": country_summary.summarize(snapshots),
        "dev_rows": tuple(
            {
                "code": v.code,
                "href": to_country(v.code),
                "summary": country_summary.summarize([v.snapshot]),
            }
            for v in views
        ),
        "truncated": any(s.truncated for s in snapshots),
    }


def _one_country(
    code: str,
    developer: str,
    select: Callable[..., str],
    query: str,
    period: registry_period.Period,
    before: registry_period.Period | None,
    limit: int,
    today: date,
    lang: str,
) -> dict[str, Any]:
    reach = auth.current_reach()
    key = request.args.get("unit", "").strip()[:80]
    вид = country_data.load(
        reach=reach,
        limit=limit,
        code=country_data.normalize_code(code),
        selection=overview_data.Selection(),
        unit_id=key,
        dates=_dates(period),
        dates_before=_dates(before) if before else None,
    )
    data = вид.snapshot
    units = country_units.load(
        reach=reach, code=вид.code, points=data.points, until=min(period.end or today, today)
    )
    column, ratings_failed = _ratings(вид.code, period, today) if вид.code else (None, False)
    открытая = units.find(key) if key else None
    история: tuple[InspectionRow, ...] = ()
    if открытая is not None and открытая.unit_id:
        история = country_units.history(reach=reach, name=открытая.name, fallback=вид.history)
    needle = query.casefold()
    in_rail = tuple(
        r
        for r in units.rows
        if not needle
        or (открытая is not None and r.key == открытая.key)
        or _unit_matches(r, needle, lang)
    )
    plans = _country_plans(вид.code)
    rx = prescriptions.country_block(вид.code)
    return {
        "view": вид,
        "data": data,
        "summary": country_summary.summarize([data]),
        "column": column,
        "ratings_failed": ratings_failed,
        "units": units,
        "partners": _partners(units.rows),
        "partners_shown": PARTNERS_SHOWN,
        "developer": developer,
        "open_row": открытая,
        "rail_open": tuple(r for r in in_rail if not r.is_closed),
        "rail_closed": tuple(r for r in in_rail if r.is_closed),
        "pick_open": открытая is not None,
        "pick_back": select(unit=""),
        "pick_title": открытая.name if открытая is not None else "",
        "history": история,
        "can_add_units": can_add_here(вид.code),
        "plans_count": len(plans["plans"]) if plans["plans_known"] else None,
        "rx_count": len(rx["rx_rows"]) if rx["rx_known"] else None,
        **{k: v for k, v in plans.items() if k.startswith("plans_act")},
        **{k: rx[k] for k in ("rx_act_hq", "rx_hq_path", "rx_partner_path")},
        "truncated": data.truncated,
        "country_name": country_title(вид.code, lang),
    }


def index_redirect(lang_in_url: bool, lang: str) -> Response | None:
    """Единственная страна без отбора девелопера — сразу в неё."""
    страны = country_data.countries(reach=auth.current_reach())
    if len(страны) == 1 and not request.args.get("dev"):
        язык = {"lang": lang} if lang_in_url else {}
        return redirect(_url("country", code=страны[0][0], **язык))
    return None
