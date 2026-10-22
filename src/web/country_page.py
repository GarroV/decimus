"""Экран «Страны» (прежде «Пиццерии»): снимок страны и история пиццерии (D260, D262, D512).

Каркас — общий шаблон «выбор слева — рабочая область справа»
(`templates/_pick_page.html`, `docs/12-web-admin.md`). Слева поиск, отбор
«Девелопер» и страны списком по алфавиту названия (код, средняя за период, пиццерий; D536);
над списком — постоянный отбор «Мои страны» (`country_filter.py`, хранится в
профиле). Выбранная страна раскрывается списком своих пиццерий и сворачивается
повторным нажатием (`fold=1`). Справа: у страны — шапка (название и период в
одной строке, сведения отдельными блоками), статистика страны и ниже список её
проверок; у пиццерии — её сведения, цифры и ниже список её проверок. Проверка из
списка и «Карточка страны» (D539, всем, кому видна страна) открываются панелью справа на
этом же экране (D527), а не отдельной страницей.
Состояние живёт в адресе: период `from` / `to`,
`unit=<ключ>` (выбранная пиццерия), `inspection=<id>` (панель проверки),
`settings=1` (панель настроек страны), `fold=1` (список пиццерий свёрнут), `dev=<девелопер>`
(отбор стран), `q=<поиск>` —
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
    country_filter,
    country_settings,
    country_summary,
    country_units,
    guard,
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
    kind_title: Callable[[str, str], str],
    card: Any = None,
) -> str | Response:
    """Экран страны `code`; `None` — вход без страны: первая в колонке или сводка девелопера.

    `card` — панель проверки из адреса (`?inspection=`), собранная тем же кодом, что
    у «Проверок» (`app._registry_panel`); без неё панель проверки закрыта.
    """
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
    все_страны = country_data.countries(reach=reach)
    страны, отбор = _filtered(все_страны, code, lang)
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
                mine=_my_countries(все_страны, отбор, lang, None),
            )
        code = в_колонке[0][0]
    period = registry_period.read(request.args, today=today)
    before = registry_period.shift(period, -1)
    unit_key = request.args.get("unit", "").strip()[:80] if not combined else ""
    folded = request.args.get("fold") == "1"

    def select(**changes: str) -> str:
        """Адрес этого же экрана с изменённым срезом; пустое и умолчания выпадают."""
        params = {
            **period.params(),
            "dev": dev,
            "q": query,
            "unit": unit_key,
            "fold": "1" if folded and not unit_key else "",
            "lang": lang,
            **changes,
        }
        if combined:
            return _url("country_index", **params)
        return _url("country", code=code or "-", **params)

    def to_country(target: str) -> str:
        """Строка колонки: тот же период, девелопер и поиск; без пиццерии и панелей.

        Повторное нажатие на уже выбранную страну (без выбранной пиццерии)
        сворачивает её список пиццерий, ещё одно — разворачивает (D536).
        """
        fold = "1" if target == code and not unit_key and not folded and not combined else ""
        return _url(
            "country", code=target, **period.params(), dev=dev, q=query, fold=fold, lang=lang
        )

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
        "mine": _my_countries(все_страны, отбор, lang, code),
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
        "kind_title": kind_title,
        "registry_path": section("registry").path,
        "combined": combined,
        "limit": limit,
        "is_hq": уК,
        "folded": folded and not unit_key,
        # Партнёр с одной страной выбора страны не видит (D508).
        "single_country": not уК and len(все_страны) <= 1,
        "added": request.args.get("added") == "1",
        "profile_failed": request.args.get("profile_failed") == "1",
        "alias_taken": request.args.get("alias_taken") == "1",
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
            card,
        ),
    )


def _filtered(
    все: tuple[tuple[str, int], ...], current: str | None, lang: str
) -> tuple[tuple[tuple[str, int], ...], tuple[str, ...]]:
    """Страны колонки по алфавиту названия и сохранённый отбор вошедшего (D536).

    Отбор сужает охват и не расширяет его; открытая адресом страна вне отбора
    остаётся в колонке (ссылка с «Главной» или от коллеги не должна вести в пустоту).
    """
    chosen = country_filter.saved()
    shown = set(country_filter.narrow(tuple(c for c, _n in все), chosen))
    if current:
        shown.add(current)
    kept = tuple((c, n) for c, n in все if c in shown)
    return tuple(sorted(kept, key=lambda пара: _alpha(пара[0], lang))), chosen


def _alpha(code: str, lang: str) -> tuple[str, str]:
    """Ключ порядка колонки: название на языке экрана без учёта регистра, затем код."""
    return ((country_title(code, lang) or code).casefold(), code)


def _my_countries(
    все: tuple[tuple[str, int], ...],
    chosen: tuple[str, ...],
    lang: str,
    current: str | None,
) -> dict[str, Any] | None:
    """Панель «Мои страны»: флажки по алфавиту, кластеры и признак действующего отбора.

    Партнёру с одной страной выбирать нечего — панели нет.
    """
    codes = tuple(c for c, _n in все)
    if len(codes) <= 1:
        return None
    on = (
        set(country_filter.narrow(codes, chosen))
        if country_filter.is_active(codes, chosen)
        else set()
    )
    return {
        "active": bool(on),
        "count": len(on),
        "total": len(codes),
        "rows": tuple(
            {"code": c, "title": country_title(c, lang) or c, "on": c in on}
            for c in sorted(codes, key=lambda x: _alpha(x, lang))
        ),
        "clusters": tuple(
            {
                "key": c.key,
                "codes": c.codes,
                "on": bool(on) and set(c.codes) == on,
            }
            for c in country_filter.clusters_of(codes)
        ),
        "action": url_for("country_filter"),
        "next": request.full_path.rstrip("?"),
        "current": current,
    }


def _rail(
    countries: tuple[tuple[str, int], ...],
    query: str,
    lang: str,
    stats: dict[str, tuple[float | None, int]],
    to_country: Callable[[str], str],
    *,
    current: str | None,
) -> tuple[dict[str, Any], ...]:
    """Строки колонки стран по алфавиту названия: код, название, пиццерий, средняя, проверок.

    Поиск — по названию на языке экрана и по коду, без учёта регистра; выбранная
    страна остаётся в колонке при любом запросе — под ней её пиццерии.
    """
    needle = query.casefold()
    rows = []
    for code, units in sorted(countries, key=lambda пара: _alpha(пара[0], lang)):
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


def _reach(rows: tuple[country_units.UnitRow, ...]) -> tuple[int, int]:
    """Сколько работающих пиццерий проверяли хоть раз и сколько их всего (D549).

    Закрытые не считаются: в них проверять нечего. Строка над списком отвечает на
    вопрос «сколько в стране ещё ни разу не видели», который раньше задавала
    галочка реестра.
    """
    живые = [r for r in rows if not r.is_closed]
    return sum(1 for r in живые if r.last_ever or r.last), len(живые)


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


def _trend(history: tuple[InspectionRow, ...]) -> float | None:
    """Движение оценки пиццерии: последняя проверка против предыдущей; одной проверки мало.

    Это разность двух уже записанных процентов, а не пересчёт оценки: оценку
    считает только движок (`CLAUDE.md`).
    """
    if len(history) < 2:
        return None
    return round(history[0].pct - history[1].pct, 1)


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
    card: Any,
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
    # Проверки страны за период, свежие сверху (D536): тот же срез, что плитки выше.
    проверки = tuple(
        sorted(data.inspections, key=lambda r: (r.inspection_date, r.pushed_at), reverse=True)
    )
    # Карточку страны видит каждый, кому видна страна (D539); правка — `space.manage`.
    can_settings = bool(вид.code)
    settings_open = can_settings and request.args.get("settings") == "1"
    card_open = bool(card is not None and card.explicit)
    return {
        "view": вид,
        "data": data,
        "summary": country_summary.summarize([data]),
        "column": column,
        "ratings_failed": ratings_failed,
        "units": units,
        "partners": _partners(units.rows),
        "developer": developer,
        "open_row": открытая,
        "rail_open": tuple(r for r in in_rail if not r.is_closed),
        "rail_closed": tuple(r for r in in_rail if r.is_closed),
        "rail_reach": _reach(units.rows),
        "pick_open": settings_open or card_open,
        "pick_back": select(inspection="", settings="", saved=""),
        "pick_title": (
            f"{t('country.settings.title', lang)} · {country_title(вид.code, lang)}"
            if settings_open
            else t("registry.drawer.title", lang)
        ),
        "settings_open": settings_open,
        "pick_wide": settings_open,
        "panel_settings": (
            country_settings.load(
                вид.code,
                developer,
                request.args.get("saved", ""),
                units=units,
                can_edit=guard.may("space.manage"),
                show_email=auth.current_tenant() == HQ_TENANT,
                can_contract=guard.may("contract.manage"),
                inspections=data.inspections,
            )
            if settings_open
            else None
        ),
        "card": card.context if card_open else None,
        "card_missing": bool(card_open and card.missing),
        "card_failed": bool(card_open and card.failed),
        "card_id": card.picked if card_open else "",
        "history": история,
        "trend": _trend(история),
        "country_inspections": проверки,
        "can_settings": can_settings,
        "settings_url": select(settings="1", inspection="", saved=""),
        "can_add_units": can_add_here(вид.code),
        "plans_count": len(plans["plans"]) if plans["plans_known"] else None,
        "rx_count": len(rx["rx_rows"]) if rx["rx_known"] else None,
        **{k: v for k, v in plans.items() if k.startswith("plans_act")},
        "rx_act_hq": rx["rx_act_hq"],
        "actions_path": section("actions").path,
        "truncated": data.truncated,
        "country_name": country_title(вид.code, lang),
    }


def index_redirect(lang_in_url: bool, lang: str) -> Response | None:
    """Единственная страна (после отбора «Мои страны») без отбора девелопера — сразу в неё."""
    страны, _ = _filtered(country_data.countries(reach=auth.current_reach()), None, lang)
    if len(страны) == 1 and not request.args.get("dev"):
        язык = {"lang": lang} if lang_in_url else {}
        return redirect(_url("country", code=страны[0][0], **язык))
    return None
