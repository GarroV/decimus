"""Экран «Обучение»: обученность пиццерий по данным iSpring (D574, D575, D578, #906).

Каркас — общий шаблон «выбор слева — рабочая область справа» (`templates/_pick_page.html`,
D474), как у «Стран»: слева «Все страны» и страны с обученностью, выбранная страна
раскрывается своими пиццериями; справа плитки, список худших сверху и курсы выбранного.
Вопрос экрана: «насколько обучены люди в пиццерии, стране, сети — и где хуже всего».

Состояние живёт в адресе: `/training` — сеть, `/training/<код страны>` — страна,
`?unit=<подразделение iSpring>` — пиццерия. Период: v1 показывает одно состояние — снимок
последней загрузки («данные на <дата>»); календарь «с — по» не нужен, пока в базе нет
истории (`docs/20-training.md`).

Ничего не считает сам: счётчики складываются, проценты берутся у суммы
(`src/domain/training_metrics.py`); читает `src/db/training_read.py`. Партнёр видит только
страны своего охвата: чужая страна в адресе — тот же 404, что у несуществующей.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from flask import Flask, abort, render_template, request, url_for

from src.db import training_read
from src.db.errors import LearningError
from src.domain import training_metrics as tm
from src.domain.training_metrics import Counters
from src.ratings.countries import country_names

from . import auth, guard, ui_lang
from .config import Settings
from .geo_names import country_title as geo_title
from .sections import section
from .texts import t

log = logging.getLogger(__name__)

#: Курсов в списке: у сети их сотни, длинный хвост экрану не нужен.
COURSE_LIMIT = 50


@dataclass(frozen=True)
class Row:
    """Строка списка: название, ссылка, обученность и цифры рядом."""

    title: str
    href: str
    pct: float | None
    assigned: int
    overdue: int
    note: str = ""


def country_title(code: str, lang: str) -> str:
    """Название страны: справочник сети, затем справочник рейтингов, затем код."""
    title = geo_title(code, lang)
    if title and title != code:
        return title
    ru, en = country_names(code)
    return ru if lang == "ru" else en


def percent_text(value: float | None) -> str:
    """Процент одной цифрой после запятой; нет данных — прочерк, а не ноль."""
    return "—" if value is None else f"{value:.1f}%"


def duration_text(seconds: float | None, lang: str) -> str:
    """Время словами человека: «12 мин», «1 ч 05 мин»; нет данных — прочерк."""
    if seconds is None:
        return "—"
    minutes = max(1, round(seconds / 60))
    hours, rest = divmod(minutes, 60)
    if not hours:
        return t("training.dur.min", lang, n=minutes)
    return t("training.dur.hour", lang, h=hours, m=f"{rest:02d}")


def _total(counters: Iterable[Counters]) -> Counters:
    return sum(counters, Counters())


def worst_first(rows: Iterable[Row]) -> tuple[Row, ...]:
    """Хуже всех — сверху; без данных — в конец, внутри равных по названию."""
    return tuple(
        sorted(rows, key=lambda r: (r.pct is None, r.pct if r.pct is not None else 0.0, r.title))
    )


def _row(title: str, href: str, counters: Counters, note: str = "") -> Row:
    return Row(title, href, tm.trained_pct(counters), counters.assigned, counters.overdue, note)


def _tiles(c: Counters, lang: str) -> tuple[dict[str, str], ...]:
    """Пять плиток: обученность, полностью обучены, просрочено, время на курс, сдали тест."""
    return (
        {
            "label": t("training.tile.trained", lang),
            "value": percent_text(tm.trained_pct(c)),
            "sub": t("training.tile.trained_sub", lang, done=c.completed, total=c.assigned),
            "hint": t("training.tile.trained_hint", lang),
        },
        {
            "label": t("training.tile.people", lang),
            "value": percent_text(tm.fully_trained_pct(c)),
            "sub": t("training.tile.people_sub", lang, done=c.people_trained, total=c.people_total),
            "hint": t("training.tile.people_hint", lang),
        },
        {
            "label": t("training.tile.overdue", lang),
            "value": str(c.overdue),
            "sub": t("training.tile.overdue_sub", lang),
            "hint": t("training.tile.overdue_hint", lang),
        },
        {
            "label": t("training.tile.time", lang),
            "value": duration_text(tm.avg_time(c), lang),
            "sub": t("training.tile.time_sub", lang, n=c.time_n),
            "hint": t("training.tile.time_hint", lang),
        },
        {
            "label": t("training.tile.pass", lang),
            "value": percent_text(tm.pass_rate(c)),
            "sub": t("training.tile.pass_sub", lang, n=c.passed + c.failed),
            "hint": t("training.tile.pass_hint", lang),
        },
    )


def _course_rows(
    courses: Iterable[training_read.CourseTotals], lang: str
) -> tuple[tuple[dict[str, Any], ...], int]:
    """Курсы по числу назначений, не больше `COURSE_LIMIT`, и сколько их всего."""
    ordered = sorted(courses, key=lambda k: (-k.counters.assigned, k.title))
    rows = tuple(
        {
            "title": k.title,
            "assigned": k.counters.assigned,
            "pct": tm.trained_pct(k.counters),
            "pct_text": percent_text(tm.trained_pct(k.counters)),
            "overdue": k.counters.overdue,
            "time_text": duration_text(tm.avg_time(k.counters), lang),
        }
        for k in ordered[:COURSE_LIMIT]
    )
    return rows, len(ordered)


def _empty(*, failed: bool) -> str:
    """Загрузки ещё не было (или база не ответила): честное пустое состояние.

    Ключи iSpring ставит главный админ на экране «Подключения» (D576): ему даём ссылку.
    """
    return render_template(
        "training/index.html",
        view=None,
        failed=failed,
        rail=(),
        keys_path=f"{section('users').path}/connections" if guard.may("keys.manage") else "",
    )


def render(*, code: str | None, lang: str) -> str:
    """Экран «Обучение»; `code` — страна из адреса, `None` — вся сеть."""
    reach = auth.current_reach()
    scope = reach.countries
    code = code.strip().upper()[:2] if code else None
    if code and scope is not None and code not in scope:
        abort(404)
    try:
        on_date = training_read.snapshot_date()
        if on_date is None:
            return _empty(failed=False)
        units = training_read.unit_totals(on_date, scope)
    except LearningError:
        log.exception("Обучение: снимок не прочитался")
        return _empty(failed=True)
    if code and not any(u.country_code == code for u in units):
        abort(404)
    return _screen(code, lang, scope, on_date, units)


def _screen(
    code: str | None,
    lang: str,
    scope: tuple[str, ...] | None,
    on_date: date,
    units: tuple[training_read.UnitTotals, ...],
) -> str:
    unit_key = request.args.get("unit", "").strip()[:64]
    picked = next(
        (u for u in units if u.department_id == unit_key and (not code or u.country_code == code)),
        None,
    )
    code = code or (picked.country_code if picked else None)
    matched = tuple(u for u in units if u.matched)
    unmatched = tuple(u for u in units if not u.matched)

    def link(country: str | None, unit: str = "") -> str:
        params: dict[str, Any] = {
            k: v for k, v in (("unit", unit), ("lang", request.args.get("lang", ""))) if v
        }
        if country:
            return url_for("training", code=country, **params)
        return url_for("training_index", **params)

    by_country: dict[str, list[training_read.UnitTotals]] = {}
    for u in units:
        by_country.setdefault(u.country_code, []).append(u)
    rail = tuple(
        {
            "code": c,
            "title": country_title(c, lang),
            "pct": percent_text(tm.trained_pct(_total(u.counters for u in us if u.matched))),
            "meta": t("training.rail.units", lang, n=len(us)),
            "href": link(c),
            "on": c == code,
            "units": tuple(
                {
                    "title": u.title,
                    "pct": percent_text(tm.trained_pct(u.counters)),
                    "href": link(c, u.department_id),
                    "on": picked is not None and u.department_id == picked.department_id,
                }
                for u in sorted(us, key=lambda x: x.title.casefold())
                if u.matched
            ),
        }
        for c, us in sorted(
            by_country.items(), key=lambda kv: country_title(kv[0], lang).casefold()
        )
    )

    if picked is not None:
        counters = picked.counters
        title = picked.title
        courses = training_read.course_totals(on_date, scope, department=picked.department_id)
        rows: tuple[Row, ...] = ()
        rows_title = ""
        lost: tuple[training_read.UnitTotals, ...] = ()
        kicker = country_title(picked.country_code, lang)
    elif code:
        in_country = [u for u in matched if u.country_code == code]
        counters = _total(u.counters for u in in_country)
        title = country_title(code, lang)
        courses = training_read.course_totals(on_date, scope, country=code)
        rows = worst_first(
            _row(u.title, link(code, u.department_id), u.counters) for u in in_country
        )
        rows_title = t("training.block.units", lang)
        lost = tuple(u for u in unmatched if u.country_code == code)
        kicker = t("training.kicker.country", lang)
    else:
        counters = _total(u.counters for u in matched)
        title = t("training.network", lang)
        courses = training_read.course_totals(on_date, scope)
        rows = worst_first(
            _row(
                country_title(c, lang),
                link(c),
                _total(u.counters for u in us if u.matched),
                t("training.rail.units", lang, n=sum(1 for u in us if u.matched)),
            )
            for c, us in by_country.items()
        )
        rows_title = t("training.block.countries", lang)
        lost = unmatched
        kicker = t("training.kicker.network", lang)

    course_rows, course_total = _course_rows(courses, lang)
    return render_template(
        "training/index.html",
        view=True,
        failed=False,
        rail=rail,
        network_href=link(None),
        network_on=code is None and picked is None,
        network_pct=percent_text(tm.trained_pct(_total(u.counters for u in matched))),
        on_date=on_date,
        title=title,
        kicker=kicker,
        tiles=_tiles(counters, lang),
        empty_counters=counters.assigned == 0,
        rows_title=rows_title,
        rows=rows,
        courses=course_rows,
        course_total=course_total,
        course_limit=COURSE_LIMIT,
        lost=tuple(
            {
                "title": u.title,
                "country": country_title(u.country_code, lang),
                "href": link(u.country_code, u.department_id),
                "pct": percent_text(tm.trained_pct(u.counters)),
                "assigned": u.counters.assigned,
            }
            for u in sorted(lost, key=lambda x: (x.country_code, x.title))
        ),
        section_path=section("training").path,
    )


def install(app: Flask, conf: Settings) -> None:
    """Повесить экран «Обучение»: сеть, страна. Заслон раздела — общий (`view.training`)."""
    path = section("training").path

    @app.get(path, endpoint="training_index")
    def training_index() -> str:
        return render(code=None, lang=ui_lang.request_lang(conf.ui_lang))

    @app.get(path + "/<code>", endpoint="training")
    def training(code: str) -> str:
        return render(code=code, lang=ui_lang.request_lang(conf.ui_lang))
