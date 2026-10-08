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
from dataclasses import dataclass
from datetime import date

from flask import Flask, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

from src.db import ratings_read as read
from src.db.errors import RatingsError
from src.db.ratings_read import REFUSED_SETTING, RatingsEditError
from src.domain.tenants import may_manage_ratings
from src.ratings import report
from src.ratings.importer import CHANNEL_WEB, OUTCOME_DUPLICATE, ImportReport, import_file
from src.ratings.links import unit_rating_url
from src.ratings.model import RatingsFormatError
from src.ratings.periods import month_period, quarter_period

from . import auth
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


@dataclass(frozen=True)
class PeriodGroup:
    """Группа выпадающего списка периода: месяцы, кварталы, периоды рейтинга РС."""

    kind: str
    options: tuple[tuple[str, str], ...]


def period_groups(
    months: tuple[date, ...], found: report.Choices, selected: str, lang: str
) -> tuple[PeriodGroup, ...]:
    """Периоды с данными (P14): ключ строит форма, руками его не набирают."""
    month_keys = [month_period(m.year, m.month).key for m in months]
    quarters = dict.fromkeys(quarter_period(m.year, (m.month - 1) // 3 + 1).key for m in months)
    rating = [(f"rs:{p.id}", p.title_ru if lang == "ru" else p.title_en) for p in found.rs_periods]
    groups = [
        PeriodGroup("month", tuple((k, k) for k in month_keys)),
        PeriodGroup("quarter", tuple((k, k.replace("-", " ")) for k in quarters)),
        PeriodGroup("rating", tuple(rating)),
    ]
    known = {key for g in groups for key, _ in g.options}
    if selected not in known:  # период по умолчанию без данных — всё равно виден выбранным
        groups.insert(0, PeriodGroup("current", ((selected, selected.replace("-Q", " Q")),)))
    return tuple(g for g in groups if g.options)


def _country_names(rows: tuple[read.CountryRow, ...], lang: str) -> dict[str, str]:
    """Имя страны из справочника рейтингов: он знает все страны снимка, `geo_names` — нет."""
    return {row.code: row.name_ru if lang == "ru" else row.name_en for row in rows}


def render_summary(conf: Settings) -> str:
    lang = _lang(conf)
    selection, found = report.select(request.args, today=date.today())
    summary = report.build(selection)
    names = _country_names(found.countries, lang)
    return render_template(
        "ratings/index.html",
        summary=summary,
        choices=found,
        selection=selection,
        periods=period_groups(read.period_months(), found, selection.period.key, lang),
        may_manage=may_manage(),
        unit_url=unit_rating_url,
        country_name=lambda code: names.get(code) or country_title(code, lang),
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

    @app.post(f"{путь}/settings")
    def ratings_settings() -> tuple[str, int]:
        if not may_manage():
            return _forbidden()
        refuse_foreign_origin()
        return _saved(conf, _save_thresholds)
