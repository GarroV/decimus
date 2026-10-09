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
from collections.abc import Callable, Mapping
from datetime import date

from flask import Flask, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.db import maps_store
from src.db import ratings_read as read
from src.db.errors import RatingsError
from src.db.ratings_read import REFUSED_SETTING, RatingsEditError
from src.domain.tenants import may_manage_ratings
from src.ratings import layout as rl
from src.ratings import maps as rmaps
from src.ratings import report
from src.ratings.importer import CHANNEL_WEB, OUTCOME_DUPLICATE, ImportReport, import_file
from src.ratings.links import unit_rating_url
from src.ratings.model import RatingsFormatError
from src.ratings.periods import KIND_RATING, ReportPeriod
from src.ratings.pointer import GOOGLE

from . import auth, ratings_calendar
from . import ratings_candles as rc
from .action_plans import FORM_OVERHEAD_BYTES
from .config import Settings
from .errors import WebTextError
from .geo_names import country_title
from .origin import refuse_foreign_origin
from .sections import section
from .texts import TEXTS, lang_or_default, t

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
    return lang_or_default(request.args.get("lang"), fallback=conf.ui_lang)


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
    return period.key


def _layout() -> tuple[rl.Block, ...]:
    """Компоновка из базы (D368). База не ответила — порядок по умолчанию и след
    в журнале: страница рейтингов не должна падать из-за расстановки блоков."""
    try:
        return rl.arrange(read.layout_rows())
    except RatingsError:
        logger.warning("Компоновка рейтингов не прочиталась — порядок по умолчанию", exc_info=True)
        return rl.arrange(())


def _layout_from_form() -> tuple[rl.Block, ...]:
    """Порядок — скрытые поля `order`, видимость — галочки `show`, сдвиг — кнопка
    `move` вида `<блок>:-1|1`. Незнакомое отбрасывает `arrange`."""
    form = request.form
    shown = set(form.getlist("show"))
    blocks = tuple(
        rl.Block(b.key, b.key in shown)
        for b in rl.arrange((key, i, True) for i, key in enumerate(form.getlist("order")))
    )
    key, _, step = (form.get("move") or "").partition(":")
    return rl.moved(blocks, key, 1 if step == "1" else -1) if step in ("1", "-1") else blocks


def _maps(
    groups: tuple[tuple[str, tuple[str, ...]], ...], until: date, before: date | None
) -> tuple[rmaps.CountryMaps, ...] | None:
    """Оценки на картах по группам сводки (кластеры или срез) на конец периода и
    изменение к концу прошлого. База не ответила — `None` и след в журнале:
    блок скажет «нет данных», страница живёт."""
    countries = tuple(c for _, members in groups for c in members)
    try:
        now = rmaps.summarize_groups(maps_store.latest(countries, until=until), groups)
        if before is None:
            return now
        was = rmaps.summarize_groups(maps_store.latest(countries, until=before), groups)
        return rmaps.with_delta(now, was)
    except RatingsError:
        logger.warning("Оценки карт не прочитались", exc_info=True)
        return None


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
    """Подпись строки сводки: кластер в срезе IMF, иначе сам срез."""
    if line.key is not None:
        return t(f"ratings.cluster.{line.key}", lang)
    if selection.group == report.GROUP_COUNTRY and selection.value:
        return country_name(selection.value)
    if selection.group == report.GROUP_CLUSTER and selection.value:
        return t(f"ratings.cluster.{selection.value}", lang)
    return selection.value or t("ratings.group.imf", lang)


def _chart(summary: report.Summary, names: list[str], lang: str) -> dict[str, object]:
    """Строки сводки со свечами: шкала общая на вид рейтинга (D384)."""
    period = (
        summary.selection.period.begin.replace(day=1),
        summary.selection.period.end.replace(day=1),
    )
    threshold = summary.thresholds["top_threshold"]
    title = TEXTS["ratings.candle.title"][lang]  # шаблон: поля заполняет `sticks`
    kinds = {}
    for kind in ("rs", "rko"):
        series = [getattr(g, f"{kind}_candles") for g in summary.groups]
        sc = rc.scale(series, threshold)
        kinds[kind] = {
            "scale": sc,
            "rows": [rc.sticks(s, sc, period=period, lang=lang, title=title) for s in series],
        }
    return {
        "names": names,
        "kinds": kinds,
        "months": [rc.month_label(m, lang) for m in summary.months],
        "width": rc.WIDTH,
        "height": rc.HEIGHT,
    }


def render_summary(conf: Settings) -> str:
    lang = _lang(conf)
    selection, found = report.select(request.args, today=date.today())
    summary = report.build(selection)
    names = _country_names(found.countries, lang)

    def country_name(code: str) -> str:
        return names.get(code) or country_title(code, lang)

    names_of_groups = [_group_name(g, selection, lang, country_name) for g in summary.groups]
    return render_template(
        "ratings/index.html",
        blocks=tuple(b.key for b in _layout() if b.visible),
        maps=_maps(
            tuple(zip(names_of_groups, (g.countries for g in summary.groups), strict=True)),
            min(selection.period.end, date.today()),
            summary.previous.end if summary.previous else None,
        ),
        map_providers=rmaps.SHOWN_PROVIDERS,
        unit_maps=_unit_maps(min(selection.period.end, date.today())),
        chart=_chart(summary, names_of_groups, lang),
        clusters=report.CLUSTERS,
        summary=summary,
        choices=found,
        selection=selection,
        calendar=ratings_calendar.build(
            selection.period, read.period_months(), found.rs_periods, lang
        ),
        previous_title=_period_title(summary.previous, found, lang),
        risk_short_names=", ".join(t(f"ratings.{kind}", lang) for kind in summary.risk_short),
        may_manage=may_manage(),
        unit_url=unit_rating_url,
        country_name=country_name,
        ratings_path=section("ratings").path,
        at_format=_AT,
    )


def render_imports(conf: Settings, *, notice: str | None = None, failure: str | None = None) -> str:
    lang = _lang(conf)
    countries = tuple(row for row in read.countries() if row.is_imf)
    names = _country_names(countries, lang)
    return render_template(
        "ratings/imports.html",
        notice=notice,
        failure=failure,
        journal=read.imports(),
        issues=read.open_issues(),
        countries=countries,
        rules=read.hard_rules(),
        layout=_layout(),
        settings=read.settings(),
        max_mb=UPLOAD_MAX_BYTES // _MB,
        ratings_path=section("ratings").path,
        country_name=lambda code: names.get(code) or country_title(code, lang),
        at_format=_AT,
    )


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
        return render_imports(conf, failure=too_big), 413
    if файл is None or not файл.filename:
        return render_imports(conf, failure=t("ratings.imports.no_file", lang)), 400
    data = файл.read(UPLOAD_MAX_BYTES + 1)
    if len(data) > UPLOAD_MAX_BYTES:
        return render_imports(conf, failure=too_big), 413
    try:
        итог = import_file(
            data, kind=None, channel=CHANNEL_WEB, actor=_actor(), file_name=файл.filename
        )
    except RatingsFormatError as exc:
        reason = _coded("ratings.error", exc.code, exc.params, lang, "ratings.error.unknown_format")
        return render_imports(conf, failure=t("ratings.imports.failed", lang, reason=reason)), 400
    except RatingsError as exc:
        logger.warning("рейтинги: загрузка %s не легла: %s", файл.filename, exc)
        return render_imports(conf, failure=t("ratings.imports.db_down", lang)), 503
    return render_imports(conf, notice=_loaded_notice(итог, lang)), 200


def _saved(conf: Settings, action: Callable[[], object]) -> tuple[str, int]:
    lang = _lang(conf)
    try:
        action()
    except RatingsEditError as exc:
        reason = _coded("ratings.refused", exc.code, exc.params, lang, "ratings.refused.db_failed")
        return render_imports(conf, failure=t("ratings.refused", lang, reason=reason)), 400
    return render_imports(conf, notice=t("ratings.saved", lang)), 200


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
        return render_summary(conf)

    @app.get(f"{путь}/imports", endpoint="ratings_imports")
    def ratings_imports() -> str | tuple[str, int]:
        if not may_manage():
            return _forbidden()
        return render_imports(conf)

    @app.post(f"{путь}/import")
    def ratings_upload() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _upload(conf)

    @app.post(f"{путь}/countries")
    def ratings_developer() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        code = (request.form.get("code") or "").strip().upper()
        developer = request.form.get("developer")
        return _saved(conf, lambda: read.set_developer(code, developer, actor=_actor()))

    @app.post(f"{путь}/hard-rules")
    def ratings_rule_add() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        form = request.form
        return _saved(
            conf,
            lambda: read.add_hard_rule(
                form.get("rating_type", ""),
                form.get("match", ""),
                form.get("pattern", ""),
                actor=_actor(),
            ),
        )

    @app.post(f"{путь}/hard-rules/<int:rule_id>/delete")
    def ratings_rule_remove(rule_id: int) -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _saved(conf, lambda: read.remove_hard_rule(rule_id))

    @app.post(f"{путь}/layout")
    def ratings_layout() -> tuple[str, int]:
        """Компоновка страницы (D368, D370) — тот же круг, что ведёт рейтинги."""
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        blocks = _layout_from_form()
        return _saved(
            conf,
            lambda: read.save_layout([(b.key, b.visible) for b in blocks], actor=_actor()),
        )

    @app.post(f"{путь}/settings")
    def ratings_settings() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _saved(conf, _save_thresholds)
