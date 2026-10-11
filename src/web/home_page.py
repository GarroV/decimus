"""Экран «Главная» (D378): по образцу новой главной Swarm Brain.

Вопрос экрана — «что в моих пиццериях требует внимания и как они проверены за
период» (D397); в первую очередь про проверки, рейтинг клиента — колонками
(D398). Партнёр видит свои пиццерии, УК — всю сеть: страница одна, различается
охват. Сверху вниз:

1. «Требует внимания» — одна карточка: стикеры доски по живым счётчикам
   (`home_board`) и под ними пиццерии, куда смотреть. Нечего показать — карточки
   нет вовсе; отказ доски остаётся строкой с ошибкой, не тишиной;
2. «Проверки за период» — итог; без проверок — одной строкой;
3. «Где нужно проверить» (точки без проверок за период) | «Последние проверки»;
4. «Топ нарушений» | «Потери по зонам», пустое скрыто;
5. «Пиццерии» — на всю строку, с порядком на самом блоке и колонками последней
   оценки РС / РКО (`home_ratings.load_latest`; сбой — прочерки и строка в
   шапке блока, экран остаётся);
6. «Мои страны» — только тому, у кого стран больше одной.

Период — один на экран: календарь «с — по» со стрелками, по умолчанию текущий
месяц (D378, тот же `registry_period`, что у «Проверок»). Срез живёт в адресе,
ссылкой делятся. «Город» и «Буква» с главной ушли: город — работа «Страны»
(D260), буква видна в таблице пиццерий.

Блок, чьи данные не прочитались, говорит об этом сам, а экран остаётся: доска и
рейтинги — не повод не показать проверки. Пустой вспомогательный блок не
показывается: «всё сделано» экрану ни о чём не говорит (D397).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from flask import render_template, request, url_for

from src.db import queries
from src.db.errors import DbError
from src.domain.tenants import HQ_TENANT

from . import auth, home_board, home_ratings, registry_period, registry_view, view
from . import overview as overview_data
from .sections import section
from .texts import t

log = logging.getLogger(__name__)

#: Сколько последних проверок показывает карточка «Последние проверки».
LATEST_COUNT = 8


@dataclass(frozen=True)
class CountryRow:
    """Строка «Моих стран»: проверки за период."""

    code: str
    units: int
    checked: int
    inspections: int
    average: float | None
    href: str


def _url(endpoint: str, **params: Any) -> str:
    """`url_for` со словарём параметров (см. `app._url`)."""
    return url_for(endpoint, **params)


def _board_href(kind: str, *, hq: bool) -> str:
    """Куда ведёт стикер: туда, где это дело делают."""
    куда = {
        home_board.REVIEW: section("registry").path,
        home_board.PLANS_REVIEW: section("actions").path,
        home_board.PLANS_DUE: section("plans").path,
        home_board.ORDERS_DUE: section("actions" if hq else "orders").path,
        home_board.RATINGS_STALE: url_for("ratings_imports"),
    }
    return куда[kind]


def _board(reach: Any) -> tuple[tuple[home_board.Sticker, ...], bool]:
    """Стикеры и то, не отказала ли база (у роли без доски — пусто и без отказа)."""
    вошедший = auth.current_account()
    if вошедший is None:
        return (), False
    who = home_board.Who(вошедший.role, auth.current_tenant())
    if not home_board.kinds_for(who):
        return (), False
    try:
        counts = home_board.load_counts(reach, who, now=datetime.now(UTC))
    except DbError as exc:
        log.warning("главная: доска не прочиталась (%s)", exc.__class__.__name__)
        return (), True
    return home_board.compose(who, counts, lambda k: _board_href(k, hq=who.hq)), False


def _latest_ratings(
    codes: tuple[str, ...] | None, until: date
) -> tuple[dict[str, tuple[float | None, float | None]], bool]:
    """Последние РС / РКО по пиццериям; сбой — пусто и отметка: главная остаётся."""
    try:
        return home_ratings.load_latest(codes, until=until), False
    except DbError as exc:
        log.warning("главная: оценки рейтинга не прочитались (%s)", exc.__class__.__name__)
        return {}, True


def render(
    *,
    lang: str,
    limit: int,
    pick: Callable[..., Any],
    item_titles: dict[str, str],
) -> str:
    today = date.today()
    period = registry_period.read(request.args, today=today)
    before = registry_period.shift(period, -1)
    reach = auth.current_reach()
    страна = request.args.get("country", "").strip().upper()[:2]
    # Страна вне охвата из адреса не сужает экран: иначе рейтинги показали бы
    # её, а проверки (их держит охват в запросе) — пустоту, без объяснения.
    if reach.countries is not None and страна not in reach.countries:
        страна = ""
    selection = overview_data.Selection(
        country=страна,
        sort=request.args.get("sort", "score").strip()[:8],
    )
    snapshot = overview_data.load(
        reach=reach,
        limit=limit,
        selection=selection,
        dates=(period.start, period.end),
        dates_before=(before.start, before.end) if before else None,
    )
    hq = auth.current_tenant() == HQ_TENANT

    def select(**изменения: str) -> str:
        """Адрес главной с изменённым срезом; пустое и умолчания из адреса выпадают."""
        параметры = {
            "country": selection.country,
            "sort": selection.sort,
            **period.params(),
            "lang": lang,
            **изменения,
        }
        живые = {к: з for к, з in параметры.items() if з and not (к == "sort" and з == "score")}
        return _url("overview", **живые)

    def в_страну(country: str, **параметры: str) -> str:
        живые = {**period.params(), "lang": lang, **параметры}
        return _url("country", code=country, **{к: з for к, з in живые.items() if з})

    codes = (selection.country,) if selection.country else reach.countries
    рейтинги, рейтинги_отказ = _latest_ratings(codes, min(period.end or today, today))
    стикеры, доска_отказ = _board(reach)

    страны = tuple(
        CountryRow(
            code=код,
            units=точек,
            checked=проверено,
            inspections=проверок,
            average=round(сумма / проверок, 1) if проверок else None,
            href=select(country=код),
        )
        for код, точек, проверено, проверок, сумма, _d in queries.country_summary(
            reach=reach, date_from=period.start, date_to=period.end
        )
        if not selection.country or код == selection.country
    )
    # Заголовок колонки РС / РКО ведёт на «Рейтинги»; суженная страна — в её срез.
    ratings_href = _url(
        "ratings", lang=lang, **({"group": "country", "value": страна} if страна else {})
    )
    порядок = pick(
        label=t("overview.sort", lang),
        empty_title=t("overview.sort.score", lang),
        current="" if selection.sort == "score" else selection.sort,
        values=tuple((код, None) for код in overview_data.ПОРЯДКИ if код != "score"),
        href=lambda значение: select(sort=значение or "score"),
        title=lambda код: t("overview.sort." + код, lang),
    )
    return render_template(
        "overview/index.html",
        data=snapshot,
        selection=selection,
        period=period,
        period_title=registry_view.period_title(period, lang),
        period_prev=registry_view.period_link(period, -1, select),
        period_next=registry_view.period_link(period, 1, select),
        period_month=select(period="", **{"from": "", "to": ""}),
        period_all=select(period=registry_period.ALL, **{"from": "", "to": ""}),
        period_is_this_month=period == registry_period.month_of(today),
        hidden_params={
            к: з
            for к, з in (("country", selection.country), ("sort", selection.sort))
            if з and з != "score"
        },
        only_country=selection.country,
        clear_country=select(country=""),
        stickers=стикеры,
        board_failed=доска_отказ,
        latest_count=LATEST_COUNT,
        ratings_href=ratings_href,
        unit_ratings=рейтинги,
        ratings_failed=рейтинги_отказ,
        countries=страны,
        sort_pick=порядок,
        registry_path=section("registry").path,
        grade_tone=view.grade_tone,
        level_tone=view.level_tone,
        lang=lang,
        country_url=в_страну if hq else None,
        item_titles=item_titles,
        unit_ids=snapshot.unit_ids,
    )
