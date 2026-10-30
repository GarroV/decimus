"""Раздел «Рейтинги» (спека 2026-10-08) и подраздел «Загрузки».

Сводку видят все вошедшие — УК и любой партнёр (D327, «рейтинги видят все»).
Загрузка, журнал и справочники — только контроль и админ УК (D319): заслон на
КАЖДОМ маршруте, набранный руками адрес отвечает 403. Расчётов здесь нет —
`src.ratings.report` собрал, экран показал.

Причины отказа показываются ключами `texts_ratings` по коду (P15): русский текст
исключения остаётся журналу и MCP и в интерфейс на другом языке не попадает.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from types import ModuleType
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response

from src.db import agg_store, maps_store
from src.db import ratings_read as read
from src.db import ratings_sync as sheet_state
from src.db.errors import RatingsError
from src.db.ratings_read import REFUSED_SETTING, RatingsEditError
from src.domain.tenants import HQ_TENANT, may_manage_ratings
from src.ratings import compare as rcompare
from src.ratings import maps as rmaps
from src.ratings import report, sheet_sync
from src.ratings import risk_sources as rsrc
from src.ratings.aggregators import glovo_link, migros_link
from src.ratings.aggregators import queue as agg_queue
from src.ratings.importer import CHANNEL_WEB, OUTCOME_DUPLICATE, ImportReport, import_file
from src.ratings.links import unit_rating_url
from src.ratings.model import RKO, RS, RatingsFormatError
from src.ratings.periods import (
    KIND_RANGE,
    KIND_RATING,
    RatingPeriod,
    ReportPeriod,
    previous_period,
)
from src.ratings.pointer import GOOGLE
from src.ratings.summary import UnitScore, ViolationBlock, ViolationFact

from . import (
    administration,
    auth,
    guard,
    ratings_calendar,
    ratings_freshness,
    ratings_nav,
    ratings_platforms,
    ratings_risk,
    ratings_sheet,
    ui_lang,
)
from . import ratings_line as rl_chart
from .action_plans import FORM_OVERHEAD_BYTES
from .config import Settings
from .errors import WebTextError
from .geo_names import country_title
from .origin import refuse_foreign_origin
from .sections import section
from .texts import TEXTS, t
from .users_view import TAB_RATINGS

logger = logging.getLogger(__name__)

UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_MB = 1024 * 1024
_SETTINGS = ("top_threshold", "risk_threshold", "risk_periods")
_AT = "%d.%m.%Y %H:%M"


def may_manage() -> bool:
    вошедший = auth.current_account()
    return вошедший is not None and may_manage_ratings(вошедший.role, вошедший.tenant)


def _forbidden() -> tuple[str, int]:
    return render_template("users/forbidden.html"), 403


def _lang(conf: Settings) -> str:
    return ui_lang.request_lang(conf.ui_lang)


def _actor() -> str:
    вошедший = auth.current_account()
    return вошедший.login if вошедший else ""


def _coded(prefix: str, code: str, params: Mapping[str, str], lang: str, fallback: str) -> str:
    """Текст причины по коду; незнакомый код — общий текст, а не русская строка исключения."""
    key = f"{prefix}.{code}"
    if key not in TEXTS:
        logger.warning("рейтинги: у причины %s нет текста %s", code, key)
        key = fallback
    try:
        return t(key, lang, **params)
    except WebTextError:  # параметра не хватило — общий текст лучше падения страницы
        logger.warning("рейтинги: текст %s не собрался из %s", key, sorted(params))
        return t(fallback, lang)


def _country_names(rows: tuple[read.CountryRow, ...], lang: str) -> dict[str, str]:
    """Имя страны из справочника рейтингов: он знает все страны снимка, `geo_names` — нет."""
    return {row.code: row.name_ru if lang == "ru" else row.name_en for row in rows}


def _period_title(period: ReportPeriod | None, found: report.Choices, lang: str) -> str | None:
    """Период словами: у периода РС — его название на языке экрана, а не ключ `rs:<id>` (P39)."""
    if period is None:
        return None
    if period.kind == KIND_RATING:
        for p in found.rs_periods:
            if f"rs:{p.id}" == period.key:
                return p.title_ru if lang == "ru" else p.title_en
    if period.kind == KIND_RANGE:
        return f"{period.begin:%d.%m.%Y} — {period.end:%d.%m.%Y}"
    return period.key


def _maps(
    groups: tuple[tuple[str, tuple[str, ...]], ...], until: date, before: date | None
) -> tuple[rmaps.CountryMaps, ...] | None:
    """Оценки на картах по группам сводки (кластеры или срез) на конец периода и
    изменение к концу прошлого. База не ответила — `None` и след в журнале:
    блок скажет «нет данных», страница живёт."""
    try:
        return rmaps.compare(groups, until=until, before=before)
    except RatingsError:
        logger.warning("Оценки карт не прочитались", exc_info=True)
        return None


def _agg_names(lang: str) -> dict[str, str]:
    """Название агрегатора на экране; незнакомый код — как есть."""
    prefix = "ratings.agg.name."
    return {key[len(prefix) :]: t(key, lang) for key in TEXTS if key.startswith(prefix)}


def _agg_failures() -> tuple[agg_store.LoadState, ...]:
    """Агрегаторы, чей последний сбор не удался, — их видно на странице, а не
    тишиной. Журнал не прочитался — пусто и след в журнале."""
    try:
        return tuple(s for s in agg_store.load_states() if s.outcome != "ok")
    except RatingsError:
        logger.warning("Журнал сбора агрегаторов не прочитался", exc_info=True)
        return ()


def _agg_pending() -> agg_store.UpdateRequest | None:
    """Заявка на обновление, которую бот ещё не выполнил. Не прочиталась — `None`
    и след в журнале: кнопка остаётся, а «уже в очереди» ответит сама заявка."""
    try:
        return agg_store.open_request()
    except RatingsError:
        logger.warning("Заявки на обновление агрегаторов не прочитались", exc_info=True)
        return None


#: Что сказать после кнопки «Обновить сейчас»: ключ в адресе → ключ текста.
_AGG_UPDATE_NOTICES = {
    "queued": "ratings.agg.update.queued",
    "already": "ratings.agg.update.already",
    "db_down": "ratings.agg.update.db_down",
}


def _unit_maps(until: date) -> dict[str, tuple[float, int]]:
    """Оценка Google по пиццериям, связанным с филиалами карт; сбой — пусто."""
    try:
        return maps_store.unit_scores(GOOGLE, until=until)
    except RatingsError:
        logger.warning("Оценки пиццерий на картах не прочитались", exc_info=True)
        return {}


def _group_name(
    line: report.GroupLine,
    selection: report.Selection,
    lang: str,
    country_name: Callable[[str], str],
) -> str:
    """Подпись строки сводки: кластер, страна девелопера или сам срез."""
    if line.level == report.LEVEL_COUNTRY and line.key:
        return country_name(line.key)
    if line.key is not None:
        return t(f"ratings.cluster.{line.key}", lang)
    if selection.group == report.GROUP_COUNTRY and selection.value:
        return country_name(selection.value)
    if selection.group == report.GROUP_CLUSTER and selection.value:
        return t(f"ratings.cluster.{selection.value}", lang)
    return selection.value or t("ratings.group.imf", lang)


@dataclass(frozen=True)
class SourceCountry:
    """Строка «По странам» раздела РС или РКО: всё, что уже посчитала сводка."""

    code: str
    score: float | None
    delta: float | None
    violations: int
    hard: int
    units: int


@dataclass(frozen=True)
class SourceView:
    """Раздел РС или РКО (D660): плитки, страны, Top/Bottom, хард — одного источника."""

    kind: str
    avg: float | None
    avg_delta: float | None
    units: int
    violations: ViolationBlock
    hard: tuple[ViolationFact, ...]
    hard_units: int
    registry: int | None
    countries: tuple[SourceCountry, ...]
    top: tuple[UnitScore, ...]
    bottom: tuple[UnitScore, ...]


def _registry_units(codes: tuple[str, ...]) -> int | None:
    """Работающих пиццерий в реестре этих стран — знаменатель плитки «Проверено».
    Реестр не прочитался — `None`, плитка покажет одно число."""
    try:
        return sum(1 for u in agg_store.units(codes) if u.working)
    except RatingsError:
        logger.warning("Реестр пиццерий для плитки «Проверено» не прочитался", exc_info=True)
        return None


def _source(summary: report.Summary, kind: str) -> SourceView:
    """Раздел источника из `report.Summary` — ни одного нового расчёта оценки."""
    is_rs = kind == RS
    block = summary.rs_cluster if is_rs else summary.rko_cluster
    by_country = summary.rs_by_country if is_rs else summary.rko_by_country
    hard = summary.rs_hard if is_rs else summary.rko_hard
    counts = summary.rs_units if is_rs else summary.rko_units
    hard_by_country = Counter(f.country for f in hard)
    rows = [
        SourceCountry(
            line.country,
            line.rs if is_rs else line.rko,
            line.rs_delta if is_rs else line.rko_delta,
            by_country[line.country].total if line.country in by_country else 0,
            hard_by_country[line.country],
            counts.get(line.country, 0),
        )
        for line in summary.lines
    ]
    # Лучшая средняя сверху; без оценки — внизу: таблица сравнивает, а не перечисляет.
    rows.sort(key=lambda r: (r.score is None, -(r.score or 0.0), r.code))
    return SourceView(
        kind=kind,
        avg=summary.total.rs if is_rs else summary.total.rko,
        avg_delta=summary.total.rs_delta if is_rs else summary.total.rko_delta,
        units=sum(counts.values()),
        violations=block,
        hard=hard,
        hard_units=len({f.unit for f in hard}),
        registry=_registry_units(summary.countries),
        countries=tuple(rows),
        top=summary.rs_top if is_rs else summary.rko_top,
        bottom=summary.rs_bottom if is_rs else summary.rko_bottom,
    )


@dataclass(frozen=True)
class _Frame:
    """Что нужно любому разделу: отбор, страны среза, период и язык."""

    lang: str
    selection: report.Selection
    found: report.Choices
    codes: tuple[str, ...]
    until: date
    previous: ReportPeriod | None
    country_name: Callable[[str], str]


def _section_data(
    key: str, frame: _Frame, *, agg_failures: tuple[agg_store.LoadState, ...]
) -> dict[str, object]:
    """Данные только открытого раздела (D660): остальные не читаются."""
    sel, lang, codes = frame.selection, frame.lang, frame.codes
    if key in (ratings_nav.RS, ratings_nav.RKO):
        kind = RS if key == ratings_nav.RS else RKO
        summary = report.build(sel, kinds=(kind,), with_risk=False)
        return {
            "src": _source(summary, kind),
            "thresholds": summary.thresholds,
            "unit_maps": _unit_maps(frame.until),
            "no_countries": not summary.countries,
        }
    if key == ratings_nav.RISK:
        summary = report.build(sel, kinds=(), with_risk=True)
        agg_names = _agg_names(lang)
        risk = ratings_risk.build(
            summary.risk,
            countries=summary.countries,
            until=frame.until,
            reach=auth.current_reach(),
            inspection_threshold=summary.thresholds["risk_threshold"],
        )
        return {
            "no_countries": not summary.countries,
            "risk": risk,
            "risk_short": summary.risk_short,
            "risk_hint": t(
                "ratings.risk.hint",
                lang,
                n=int(summary.thresholds["risk_periods"]),
                x=f"{summary.thresholds['risk_threshold']:.1f}",
                agg=rsrc.AGG_WINDOW,
                insp=rsrc.INSPECTION_WINDOW,
                wolt=f"{rsrc.AGG_THRESHOLDS['wolt']:.1f}",
                glovo=f"{rsrc.AGG_THRESHOLDS['glovo']:.0f}",
                share=round(rsrc.AGG_OTHER_SHARE * 100),
            ),
            "risk_unread": ", ".join(t(f"ratings.risk.unread.{k}", lang) for k in risk.unread),
            "risk_sources": ratings_risk.source_names(agg_names, lang),
            "risk_short_names": ", ".join(
                t(f"ratings.{kind}", lang) for kind in summary.risk_short
            ),
        }
    if key == ratings_nav.COMPARE:
        return {"no_countries": not codes, "comparison": rcompare.build(sel, frame.found)}
    if key == ratings_nav.MAPS:
        groups_lines, _ = report.build_groups(sel, frame.found)
        groups = tuple(
            (_group_name(g, sel, lang, frame.country_name), g.countries) for g in groups_lines
        )
        maps = _maps(groups, frame.until, frame.previous.end if frame.previous else None)
        return {
            "no_countries": not codes,
            "maps": maps if maps and any(m.as_of for m in maps) else (),
            "map_names": [name for name, _ in groups],
            "map_providers": rmaps.SHOWN_PROVIDERS,
            "map_units": ratings_platforms.build_maps(codes, today=date.today()),
            "agg_names": _agg_names(lang),
        }
    if key == ratings_nav.AGG:
        agg_names = _agg_names(lang)
        return {
            "no_countries": not codes,
            "agg": ratings_platforms.build_agg(codes, until=frame.until, today=date.today()),
            "agg_names": agg_names,
            "agg_failures": agg_failures,
            "agg_failed_names": ", ".join(
                agg_names.get(f.aggregator, f.aggregator) for f in agg_failures
            ),
            "agg_pending": _agg_pending() if may_manage() else None,
            "agg_update_notice": _AGG_UPDATE_NOTICES.get(request.args.get("agg", "")),
            "open_country": (request.values.get("country") or "").strip().upper(),
            "link_platforms": LINK_PLACEHOLDERS,
        }
    return {"no_countries": not codes}  # «Оценки клиентов»: источника ещё нет


def render_section(
    conf: Settings, key: str, *, notice: str | None = None, failure: str | None = None
) -> str:
    """Раздел «Рейтингов» (D660): шапка, отбор, подменю и данные открытого раздела."""
    lang = _lang(conf)
    is_hq = auth.current_tenant() == HQ_TENANT
    if key not in ratings_nav.visible(is_hq):
        abort(404)
    today = date.today()
    selection, found = report.select(request.args, today=today)
    names = _country_names(found.countries, lang)

    def country_name(code: str) -> str:
        return names.get(code) or country_title(code, lang)

    codes = report.group_countries(selection, found.countries)
    previous = previous_period(selection.period, rs_periods=found.rs_periods)
    frame = _Frame(
        lang, selection, found, codes, min(selection.period.end, today), previous, country_name
    )
    root = section("ratings").path
    rows = ratings_freshness.safe_rows()
    agg_failures = _agg_failures() if key == ratings_nav.AGG else ()
    data = _section_data(key, frame, agg_failures=agg_failures)
    agg_names = _agg_names(lang)
    return render_template(
        "ratings/index.html",
        section_key=key,
        subnav=ratings_nav.items(
            root, is_hq=is_hq, current=key, selection=selection, lang=lang, rows=rows
        ),
        section_title=t(f"ratings.sec.{key}", lang),
        section_line=ratings_freshness.section_line(rows, key, lang),
        section_dot=ratings_freshness.section_status(rows, key),
        freshness=ratings_freshness.lines_of(rows, lang, agg_names),
        notice=notice,
        failure=failure,
        clusters=report.CLUSTERS,
        score_tone=rl_chart.tone,
        choices=found,
        selection=selection,
        calendar=ratings_calendar.build(
            selection.period,
            read.period_months(),
            found.rs_periods,
            lang,
            tuple(RatingPeriod(*p) for p in read.rko_periods()),
        ),
        previous_title=_period_title(previous, found, lang),
        may_manage=may_manage(),
        admin_ratings_url=admin_url(),
        unit_url=unit_rating_url,
        country_name=country_name,
        ratings_path=root,
        at_format=_AT,
        **data,
    )


#: Блоки вкладки «Рейтинги» в «Администрировании» (D654): код — это `?block=` и пояснение к форме.
BLOCK_SHEET = "sheet"
BLOCK_UPLOAD = "upload"
BLOCK_JOURNAL = "journal"
BLOCK_ISSUES = "issues"
BLOCK_DEVELOPERS = "developers"
BLOCK_RULES = "rules"
BLOCK_SETTINGS = "settings"
BLOCKS = (
    BLOCK_SHEET,
    BLOCK_UPLOAD,
    BLOCK_JOURNAL,
    BLOCK_ISSUES,
    BLOCK_DEVELOPERS,
    BLOCK_RULES,
    BLOCK_SETTINGS,
)


def admin_url(block: str = "", **extra: str) -> str:
    """Адрес вкладки «Рейтинги» (с открытым блоком); язык — из текущего адреса."""
    return administration.url(TAB_RATINGS, block=block, **extra)


def _block_states(
    lang: str,
    *,
    sheet: ratings_sheet.Block,
    journal: tuple[read.ImportRow, ...],
    issues: tuple[read.IssueRow, ...],
    countries: tuple[read.CountryRow, ...],
    rules: tuple[tuple[int, str, str, str], ...],
    settings: Mapping[str, float],
) -> dict[str, tuple[str, bool]]:
    """Короткая строка состояния для каждого блока: `(текст, требует_внимания)`."""

    def at(moment: object) -> str:
        return f"{moment:{_AT}}" if moment else "—"

    if not sheet.configured:
        sheet_line = (t("ratings.admin.sheet.off", lang), False)
    elif sheet.unreadable:
        sheet_line = (t("ratings.sheet.unreadable", lang), True)
    elif sheet.failed:
        sheet_line = (t("ratings.admin.sheet.failed", lang, n=sheet.failed), True)
    elif sheet.last_at:
        sheet_line = (t("ratings.sheet.last", lang, at=at(sheet.last_at)), False)
    else:
        sheet_line = (t("ratings.sheet.never", lang), False)
    last = journal[0] if journal else None
    with_dev = sum(1 for c in countries if c.developer)
    thresholds = [
        f"{t('ratings.settings.' + key, lang)} {settings[key]:g}"
        for key in _SETTINGS
        if key in settings
    ]
    return {
        BLOCK_SHEET: sheet_line,
        BLOCK_UPLOAD: (
            t("ratings.admin.upload.last", lang, at=at(last.at))
            if last
            else t("ratings.journal.empty", lang),
            False,
        ),
        BLOCK_JOURNAL: (t("ratings.admin.journal.state", lang, n=len(journal)), False),
        BLOCK_ISSUES: (
            (t("ratings.admin.issues.some", lang, n=len(issues)), True)
            if issues
            else (t("ratings.admin.issues.none", lang), False)
        ),
        BLOCK_DEVELOPERS: (
            t("ratings.admin.developers.state", lang, set=with_dev, total=len(countries)),
            False,
        ),
        BLOCK_RULES: (t("ratings.admin.rules.state", lang, n=len(rules)), False),
        BLOCK_SETTINGS: (" · ".join(thresholds) or "—", False),
    }


def render_imports(
    conf: Settings,
    *,
    block: str = "",
    notice: str | None = None,
    failure: str | None = None,
) -> str:
    """Вкладка «Рейтинги» в «Администрировании»: список блоков настроек, выбранный — в панели.
    Ответ любого действия (загрузка, правило, порог…) — тоже она, с открытым блоком и исходом."""
    lang = _lang(conf)
    countries = tuple(row for row in read.countries() if row.is_imf)
    names = _country_names(countries, lang)
    journal = read.imports()
    issues = read.open_issues()
    rules = read.hard_rules()
    settings = read.settings()
    sheet = ratings_sheet.build(lang)
    states = _block_states(
        lang,
        sheet=sheet,
        journal=journal,
        issues=issues,
        countries=countries,
        rules=rules,
        settings=settings,
    )
    return render_template(
        "administration/ratings.html",
        block=block,
        split_open=bool(block),
        split_back=admin_url(),
        split_wide=block in (BLOCK_SHEET, BLOCK_JOURNAL, BLOCK_ISSUES),
        link=admin_url,
        blocks=[(key, *states[key]) for key in BLOCKS],
        notice=notice,
        failure=failure,
        journal=journal,
        issues=issues,
        countries=countries,
        rules=rules,
        settings=settings,
        sheet=sheet,
        sheet_every_h=sheet_sync.SYNC_EVERY_SEC // 3600,
        sheet_notice=ratings_sheet.NOTICES.get(request.args.get(ratings_sheet.ARG, "")),
        max_mb=UPLOAD_MAX_BYTES // _MB,
        ratings_path=section("ratings").path,
        country_name=lambda code: names.get(code) or country_title(code, lang),
        at_format=_AT,
        **administration.nav(TAB_RATINGS),
    )


def show_admin(conf: Settings) -> tuple[str, int]:
    """GET `/administration?tab=ratings[&block=<код>]`."""
    block = (request.args.get("block") or "").strip()
    if block and block not in BLOCKS:
        abort(404)
    return render_imports(conf, block=block), 200


#: Площадки, к которым пиццерия привязывается ссылкой: модуль с `link_by_url` и ключ
#: текста «плохая ссылка» у этой площадки (#717).
_LINKERS: dict[str, tuple[ModuleType, str]] = {
    "glovo": (glovo_link, "bad_url"),
    "migros_yemek": (migros_link, "bad_url_migros"),
}
#: Подсказка в поле ссылки — для шаблона экрана.
LINK_PLACEHOLDERS = {
    "glovo": "https://glovoapp.com/…/stores/…",
    "migros_yemek": "https://www.migros.com.tr/yemek/…",
}


def _link_point(conf: Settings) -> tuple[str, int]:
    """Привязать пиццерию к площадке по ссылке на страницу магазина (Glovo,
    Migros Yemek — #717). Итог — одной строкой над таблицей; никому ничего не
    отправляется."""
    lang = _lang(conf)
    aggregator = (request.form.get("aggregator") or "glovo").strip()
    if aggregator not in _LINKERS:
        return render_section(
            conf, ratings_nav.AGG, failure=t("ratings.coverage.link.failed", lang)
        ), 400
    linker, bad_url = _LINKERS[aggregator]
    unit_id = (request.form.get("dodo_id") or "").strip().lower()
    today = date.today()
    try:
        unit = next((u for u in agg_store.units() if u.dodo_id == unit_id), None)
        result, point, rating = linker.link_by_url(
            unit, request.form.get("url") or "", agg_store.point_keys(aggregator), today
        )
        if point is not None:
            agg_store.save([point], [rating] if rating else [])
    except RatingsError:
        logger.warning("рейтинги: привязка %s не легла", aggregator, exc_info=True)
        return render_section(
            conf, ratings_nav.AGG, failure=t("ratings.coverage.db_down", lang)
        ), 503
    platform = _agg_names(lang).get(aggregator, aggregator)
    if result.code == glovo_link.OK and unit is not None:
        notice = t("ratings.coverage.link.ok", lang, platform=platform, name=unit.name)
        return render_section(conf, ratings_nav.AGG, notice=notice), 200
    code = bad_url if result.code == glovo_link.BAD_URL else result.code
    reason = _coded("ratings.coverage.link", code, {}, lang, "ratings.coverage.link.failed")
    return render_section(conf, ratings_nav.AGG, failure=reason), 400


def _loaded_notice(итог: ImportReport, lang: str) -> str:
    fmt = _coded("ratings.format", итог.format, {}, lang, "ratings.imports.file")
    if итог.chunk_index is not None and итог.chunk_of is not None:
        fmt = f"{fmt} ({t('ratings.chunk', lang, k=итог.chunk_index, n=итог.chunk_of)})"
    if итог.outcome == OUTCOME_DUPLICATE:
        at = f"{итог.loaded_at:{_AT}}" if итог.loaded_at else "—"
        return t("ratings.imports.duplicate", lang, at=at)
    return t(
        "ratings.imports.loaded",
        lang,
        fmt=fmt,
        a=итог.accepted,
        u=итог.updated,
        s=итог.skipped,
        m=итог.unmatched,
    )


def _upload(conf: Settings) -> tuple[str, int]:
    lang = _lang(conf)
    request.max_content_length = UPLOAD_MAX_BYTES + FORM_OVERHEAD_BYTES
    too_big = t("ratings.imports.too_big", lang, mb=UPLOAD_MAX_BYTES // _MB)
    try:
        файл = request.files.get("file")
    except RequestEntityTooLarge:
        return render_imports(conf, block=BLOCK_UPLOAD, failure=too_big), 413
    if файл is None or not файл.filename:
        return render_imports(
            conf, block=BLOCK_UPLOAD, failure=t("ratings.imports.no_file", lang)
        ), 400
    data = файл.read(UPLOAD_MAX_BYTES + 1)
    if len(data) > UPLOAD_MAX_BYTES:
        return render_imports(conf, block=BLOCK_UPLOAD, failure=too_big), 413
    try:
        итог = import_file(
            data, kind=None, channel=CHANNEL_WEB, actor=_actor(), file_name=файл.filename
        )
    except RatingsFormatError as exc:
        reason = _coded("ratings.error", exc.code, exc.params, lang, "ratings.error.unknown_format")
        return render_imports(
            conf, block=BLOCK_UPLOAD, failure=t("ratings.imports.failed", lang, reason=reason)
        ), 400
    except RatingsError as exc:
        logger.warning("рейтинги: загрузка %s не легла: %s", файл.filename, exc)
        return render_imports(
            conf, block=BLOCK_UPLOAD, failure=t("ratings.imports.db_down", lang)
        ), 503
    return render_imports(conf, block=BLOCK_UPLOAD, notice=_loaded_notice(итог, lang)), 200


def _saved(conf: Settings, block: str, action: Callable[[], object]) -> tuple[str, int]:
    lang = _lang(conf)
    try:
        action()
    except RatingsEditError as exc:
        reason = _coded("ratings.refused", exc.code, exc.params, lang, "ratings.refused.db_failed")
        return render_imports(
            conf, block=block, failure=t("ratings.refused", lang, reason=reason)
        ), 400
    return render_imports(conf, block=block, notice=t("ratings.saved", lang)), 200


def _threshold_values() -> dict[str, float]:
    """Пороги из формы; пустое поле не трогается, не число — отказ кодом (P15)."""
    values: dict[str, float] = {}
    for key in _SETTINGS:
        raw = (request.form.get(key) or "").strip().replace(",", ".")
        if not raw:
            continue
        try:
            value = float(raw)
        except ValueError:
            value = math.nan
        if not math.isfinite(value):
            raise RatingsEditError(f"Порог «{key}» — не число", REFUSED_SETTING)
        values[key] = value
    return values


def _save_thresholds() -> None:
    for key, value in _threshold_values().items():
        read.set_setting(key, value, actor=_actor())


def install(app: Flask, conf: Settings) -> None:
    путь = section("ratings").path

    @app.get(путь, endpoint="ratings")
    def ratings_index() -> str:
        """Голый `/ratings` — первый раздел (D660)."""
        return render_section(conf, ratings_nav.DEFAULT)

    # Только известные разделы: остальной `/ratings/<что-то>` — свои маршруты или 404.
    names = ",".join(ratings_nav.SECTIONS)

    @app.get(f"{путь}/<any({names}):key>", endpoint="ratings_section")
    def ratings_section(key: str) -> str:
        return render_section(conf, key)

    @app.get(f"{путь}/coverage", endpoint="ratings_coverage")
    def ratings_coverage() -> Response:
        """Старая страница охвата (D660): «по пиццериям» ушло внутрь «Агрегаторов»."""
        args = {k: v for k, v in request.args.items() if k in ("country", "lang")}
        query = f"?{urlencode(args)}" if args else ""
        return redirect(f"{request.script_root}{путь}/{ratings_nav.AGG}{query}", code=302)

    @app.post(f"{путь}/coverage/link")
    @guard.action("ratings.manage")
    def ratings_coverage_link() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _link_point(conf)

    @app.get(f"{путь}/imports", endpoint="ratings_imports")
    def ratings_imports() -> Response | tuple[str, int]:
        """Старый адрес «Загрузок» (D654): настройки переехали в «Администрирование»."""
        if not may_manage():
            return _forbidden()
        return redirect(admin_url(), code=302)

    @app.post(f"{путь}/import")
    @guard.action("ratings.manage")
    def ratings_upload() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _upload(conf)

    @app.post(f"{путь}/countries")
    @guard.action("ratings.manage")
    def ratings_developer() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        code = (request.form.get("code") or "").strip().upper()
        developer = request.form.get("developer")
        return _saved(
            conf, BLOCK_DEVELOPERS, lambda: read.set_developer(code, developer, actor=_actor())
        )

    @app.post(f"{путь}/hard-rules")
    @guard.action("ratings.manage")
    def ratings_rule_add() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        form = request.form
        return _saved(
            conf,
            BLOCK_RULES,
            lambda: read.add_hard_rule(
                form.get("rating_type", ""),
                form.get("match", ""),
                form.get("pattern", ""),
                actor=_actor(),
            ),
        )

    @app.post(f"{путь}/hard-rules/<int:rule_id>/delete")
    @guard.action("ratings.manage")
    def ratings_rule_remove(rule_id: int) -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _saved(conf, BLOCK_RULES, lambda: read.remove_hard_rule(rule_id))

    @app.post(f"{путь}/aggregators/update")
    @guard.action("ratings.manage")
    def ratings_agg_update() -> Response | tuple[str, int]:
        """Кнопка «Обновить сейчас» (D420): та же заявка, что у Claude; собирает бот.
        Назад — на ту же сводку (период и срез из адреса), с пометкой исхода."""
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        try:
            asked = agg_queue.ask(None, by=_actor())
            outcome = "queued" if asked.created else "already"
        except RatingsError:
            logger.warning("рейтинги: заявка на обновление агрегаторов не легла", exc_info=True)
            outcome = "db_down"
        # Исход виден в разделе «Агрегаторы»: возвращаем человека туда, с тем же отбором.
        args = {**request.args.to_dict(), "agg": outcome}
        return redirect(
            f"{request.script_root}{путь}/{ratings_nav.AGG}?{urlencode(args)}", code=303
        )

    @app.post(f"{путь}/sheet-sync")
    @guard.action("ratings.manage")
    def ratings_sheet_sync() -> Response | tuple[str, int]:
        """Кнопка «Забрать сейчас» (D464): заявка, которую выполняет бот. Назад — на
        «Загрузки» с пометкой исхода."""
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        try:
            _, created = sheet_state.request_sync(by=_actor())
            outcome = "queued" if created else "already"
        except RatingsError:
            logger.warning("рейтинги: заявка на забор таблицы не легла", exc_info=True)
            outcome = "db_down"
        return redirect(
            admin_url(BLOCK_SHEET, **{ratings_sheet.ARG: outcome}),
            code=303,
        )

    @app.post(f"{путь}/settings")
    @guard.action("ratings.manage")
    def ratings_settings() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _saved(conf, BLOCK_SETTINGS, _save_thresholds)
