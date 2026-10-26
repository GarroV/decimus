"""Экран «Главная» (D378): по образцу новой главной Swarm Brain.

Вопрос экрана — «что в моих пиццериях требует внимания и как они проверены за
период» (D398); в первую очередь про проверки, рейтинг клиента — колонками
(D399). Партнёр видит свои пиццерии, УК — всю сеть: страница одна, различается
охват. Сверху вниз:

Блоки (D418, D557) — полоса «Требует внимания» во всю ширину; под ней слева панель
фильтров, справа большой блок «Рейтинги»; второй ряд — три карточки одной высоты
(списки урезаны по числу строк, «ещё N →»); ниже таблица «Пиццерии» на всю ширину:

1. «Требует внимания» — полоса: стикеры доски по живым счётчикам
   (`home_board`) и под ними пиццерии, куда смотреть. Нечего показать — карточки
   нет вовсе; отказ доски остаётся строкой с ошибкой, не тишиной;
2. «Проверки за период» — итог; без проверок — одной строкой;
3. «Рейтинги» — РС, РКО, карты и агрегаторы: колонки по срезу — кластеры D502, страны
   выбранного кластера (D583) или пиццерии выбранной страны (D584) (`home_ratings_block`);
4. «Топ нарушений», «Потери по зонам» — без данных пустое состояние, сетка не ломается;
5. «Пиццерии» — таблица с колонками последней оценки РС / РКО
   (`home_ratings.load_latest`; сбой — прочерки и строка в шапке блока, экран
   остаётся). «Последних проверок» нет: список проверок — и есть эта таблица (D471).

Срез живёт в панели фильтров слева вверху (D557) и действует на весь экран,
верхние блоки тоже: период (календарь «с — по» со стрелками, по умолчанию текущий
месяц, тот же `registry_period`, что у «Проверок»), кластер (CEE / Турция / Кавказ / «Остальные
страны» из `ratings.countries.cluster`), у УК — бизнес-девелопер (D551), страна,
порядок таблицы. Кластер или девелопер сужает страны выборки; страна — одну из них.
Срез в адресе, ссылкой делятся. «Город» и «Буква» с главной ушли: город — работа
«Страны» (D260), буква видна в таблице.
«Где нужно проверить» живёт в «Проверках» (D418).

Блок, чьи данные не прочитались, говорит об этом сам, а экран остаётся: доска и
рейтинги — не повод не показать проверки. Пустой вспомогательный блок не
показывается: «всё сделано» экрану ни о чём не говорит (D398).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from flask import render_template, request, url_for

from src.db import mcp_access, ratings_read
from src.db.errors import DbError
from src.domain.tenants import HQ_TENANT
from src.ratings import report

from . import (
    auth,
    home_board,
    home_ratings,
    home_ratings_block,
    registry_period,
    registry_view,
    view,
)
from . import overview as overview_data
from .geo_names import country_title
from .sections import section
from .texts import t

log = logging.getLogger(__name__)


#: Сколько строк каждого списка влезает в карточку целиком (D471): остальное — «ещё N →».
#: Нижний ряд карточек выше верхнего (D507): «Топ нарушений» вмещает больше строк.
ATTENTION_ROWS = 6
TOP_ROWS = 7
PROCESS_ROWS = 8


def _url(endpoint: str, **params: Any) -> str:
    """`url_for` со словарём параметров (см. `app._url`)."""
    return url_for(endpoint, **params)


def _board_href(kind: str) -> str:
    """Куда ведёт стикер: туда, где это дело делают."""
    действия = section("actions").path
    куда = {
        home_board.REVIEW: section("registry").path,
        home_board.PLANS_REVIEW: f"{действия}?tab=plans",
        home_board.PLANS_DUE: f"{действия}?tab=plans",
        home_board.ORDERS_DUE: f"{действия}?tab=prescriptions",
        home_board.RATINGS_STALE: f"{section('administration').path}?tab=ratings",
        home_board.MCP_RELINK: f"{section('settings').path}?tile=claude",
    }
    return куда[kind]


def _board(reach: Any) -> tuple[tuple[home_board.Sticker, ...], bool]:
    """Стикеры и то, не отказала ли база (у роли без доски — пусто и без отказа)."""
    вошедший = auth.current_account()
    if вошедший is None or not home_board.SHOWN:
        return (), False
    who = home_board.Who(вошедший.role, auth.current_tenant())
    объявления = _announcements(вошедший.id)
    if not home_board.kinds_for(who):
        return объявления, False
    try:
        counts = home_board.load_counts(reach, who, now=datetime.now(UTC))
    except DbError as exc:
        log.warning("главная: доска не прочиталась (%s)", exc.__class__.__name__)
        return объявления, True
    return (*объявления, *home_board.compose(who, counts, _board_href)), False


def _announcements(user_id: str) -> tuple[home_board.Sticker, ...]:
    """Объявления доски (D629); ключ не прочитался — без объявления, главная живёт."""
    try:
        выпущен = mcp_access.live_token_issued_at(user_id)
    except DbError as exc:
        log.warning("главная: ключ Claude для объявления не прочитан (%s)", exc.__class__.__name__)
        return ()
    return home_board.announcements(выпущен, _board_href)


def _latest_ratings(
    codes: tuple[str, ...] | None, until: date
) -> tuple[dict[str, tuple[float | None, float | None]], bool]:
    """Последние РС / РКО по пиццериям; сбой — пусто и отметка: главная остаётся."""
    try:
        return home_ratings.load_latest(codes, until=until), False
    except DbError as exc:
        log.warning("главная: оценки рейтинга не прочитались (%s)", exc.__class__.__name__)
        return {}, True


Groups = dict[str, tuple[str, ...]]


def _groups(countries: tuple[str, ...] | None) -> tuple[Groups, Groups]:
    """Кластеры и девелоперы со своими странами в охвате; сбой чтения — пусто.

    Сопоставление страна → кластер и страна → бизнес-девелопер ведёт справочник
    рейтингов; страны вне него никуда не попадают. Пусто — фильтра на экране нет,
    сам экран остаётся.
    """
    try:
        rows = tuple(
            r for r in ratings_read.countries() if countries is None or r.code in countries
        )
    except DbError as exc:
        log.warning("главная: кластеры стран не прочитались (%s)", exc.__class__.__name__)
        return {}, {}
    clusters = {
        key: members
        for key in report.CLUSTERS
        if (members := tuple(r.code for r in rows if r.cluster == key))
    }
    developers: Groups = {}
    for r in sorted(rows, key=lambda r: (r.developer or "", r.code)):
        if r.developer and r.developer.strip():
            developers[r.developer.strip()] = (*developers.get(r.developer.strip(), ()), r.code)
    return clusters, developers


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
    full_reach = auth.current_reach()
    кластеры, девелоперы = _groups(full_reach.countries)
    # Девелопер — фильтр УК (D551): он сам выбирает, чьи страны смотреть.
    if auth.current_tenant() != HQ_TENANT:
        девелоперы = {}
    кластер = request.args.get("cluster", "").strip().upper()
    if кластер not in кластеры:
        кластер = ""
    девелопер = "" if кластер else request.args.get("developer", "").strip()
    if девелопер not in девелоперы:
        девелопер = ""
    # Кластер или девелопер сужает страны всей выборки (D471, D551); доска заданий
    # не срез — она по полному охвату вошедшего.
    срез = кластеры.get(кластер) or девелоперы.get(девелопер)
    reach = replace(full_reach, countries=срез) if срез else full_reach
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

    def select(**изменения: str) -> str:
        """Адрес главной с изменённым срезом; пустое и умолчания из адреса выпадают."""
        параметры = {
            "cluster": кластер,
            "developer": девелопер,
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

    def в_реестр() -> str:
        """Реестр проверок с тем же периодом и страной: куда ведёт «ещё N →»."""
        живые = {**period.params(), "lang": lang, "country": selection.country}
        return _url("registry", **{к: з for к, з in живые.items() if з})

    codes = (selection.country,) if selection.country else reach.countries
    рейтинги, рейтинги_отказ = _latest_ratings(codes, min(period.end or today, today))
    стикеры, доска_отказ = _board(full_reach)
    # Блок «Рейтинги» (D418): среднее группы считают «Рейтинги», здесь — только показ.
    # Колонки разворачиваются по срезу (D583, D584): кластер — по странам, страна — по
    # пиццериям в порядке «Сортировки»; пиццерия ведёт в «Страны» по id её проверок.
    коды = snapshot.unit_codes
    проверена = {коды[p.unit]: p.when for p in snapshot.points if p.unit in коды}
    ид_по_коду = {коды[имя]: ид for имя, ид in snapshot.unit_ids.items() if имя in коды}
    блок_рейтингов = home_ratings_block.load(
        scope=reach.countries,
        country=страна,
        cluster=кластер,
        period=period,
        today=today,
        sort=selection.sort,
        inspected=проверена,
    )

    # Заголовок колонки РС / РКО ведёт на «Рейтинги»; суженная страна — в её срез.
    ratings_href = _url(
        "ratings", lang=lang, **({"group": "country", "value": страна} if страна else {})
    )
    # Страна — выпадающим списком в панели фильтров (D471): страны выборки (охват и
    # кластер), пустое значение — все. Одна страна — выбирать нечего, списка нет.
    выбор_страны = (
        pick(
            label="",
            empty_title=t("home.country.all", lang),
            current=selection.country,
            values=snapshot.countries,
            href=lambda значение: select(country=значение),
            title=lambda код: country_title(код, lang),
        )
        if len(snapshot.countries) > 1
        else None
    )
    выбор_кластера = (
        pick(
            label="",
            empty_title=t("home.cluster.all", lang),
            current=кластер,
            values=tuple((ключ, len(страны)) for ключ, страны in кластеры.items()),
            href=lambda значение: select(cluster=значение, developer="", country=""),
            title=lambda ключ: t("ratings.cluster." + ключ, lang),
        )
        if len(кластеры) > 1
        else None
    )
    выбор_девелопера = (
        pick(
            label="",
            empty_title=t("home.developer.all", lang),
            current=девелопер,
            values=tuple((имя, len(страны)) for имя, страны in девелоперы.items()),
            href=lambda значение: select(developer=значение, cluster="", country=""),
            title=lambda имя: имя,
        )
        if len(девелоперы) > 1
        else None
    )
    порядок = pick(
        label="",
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
        period_quick=registry_view.period_quick(period, today, lang, select),
        hidden_params={
            к: з
            for к, з in (
                ("cluster", кластер),
                ("developer", девелопер),
                ("country", selection.country),
                ("sort", selection.sort),
            )
            if з and з != "score"
        },
        only_country=selection.country,
        attention_rows=ATTENTION_ROWS,
        top_rows=TOP_ROWS,
        process_rows=PROCESS_ROWS,
        registry_all=в_реестр(),
        stickers=стикеры,
        board_failed=доска_отказ,
        ratings_href=ratings_href,
        ratings_block=блок_рейтингов,
        rb_unit_ids=ид_по_коду,
        ratings_block_href=_url("ratings", lang=lang, **dict(блок_рейтингов.link)),
        unit_ratings=рейтинги,
        ratings_failed=рейтинги_отказ,
        cluster_pick=выбор_кластера,
        developer_pick=выбор_девелопера,
        country_pick=выбор_страны,
        sort_pick=порядок,
        registry_path=section("registry").path,
        grade_tone=view.grade_tone,
        level_tone=view.level_tone,
        lang=lang,
        country_url=в_страну,
        item_titles=item_titles,
        unit_ids=snapshot.unit_ids,
    )
