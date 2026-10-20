"""Чтение обучения для экрана «Обучение» (схема `learning`, миграция 0085; D574, D578).

Читают все роли, у которых есть раздел (`view.training`); охват по странам ставит веб
(`auth.current_reach().countries`): `None` — вся сеть, кортеж — только эти страны, пустой —
ничего. Данные — снимок последней загрузки; экран говорит «на дату», а не «за период».

Страна и сеть здесь не хранятся: экран складывает счётчики пиццерий (`Counters.__add__`),
проценты берутся у суммы (`src/domain/training_metrics.py`). В счёт страны и сети идут
только сопоставленные пиццерии; несопоставленные отдаются отдельно (`kind` пиццерии без
`unit_dodo_id`) и показываются списком.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import psycopg

from src.domain.training_metrics import COLUMNS, Counters

from .config import check_environment
from .errors import LearningError
from .pool import connection
from .training_names import COURSE_COLUMNS

_UNIT_SELECT = ", ".join(f"t.{c}" for c in COLUMNS)
_UNITS_SQL = (
    f"select d.ispring_id, d.title, d.country_code, d.unit_dodo_id, {_UNIT_SELECT} "  # noqa: S608
    "from learning.unit_totals t join learning.departments d on d.ispring_id = t.department_id "
    "where t.sync_date = %(on_date)s and d.kind = 'pizzeria' "
    "and (%(countries)s::text[] is null or d.country_code = any(%(countries)s))"
)
_SUMS = ", ".join(f"sum(c.{col})" for col in COURSE_COLUMNS)
_COURSES_SQL = (
    f"select c.course_id, k.title, {_SUMS} "  # noqa: S608
    "from learning.unit_courses c "
    "join learning.departments d on d.ispring_id = c.department_id "
    "join learning.courses k on k.course_id = c.course_id "
    "where c.sync_date = %(on_date)s and d.kind = 'pizzeria' "
    "and (%(countries)s::text[] is null or d.country_code = any(%(countries)s)) "
    "and (%(country)s::text is null or d.country_code = %(country)s) "
    "and (%(department)s::text is null or d.ispring_id = %(department)s) "
    "and (%(department)s::text is not null or d.unit_dodo_id is not null) "
    "group by c.course_id, k.title"
)


@dataclass(frozen=True)
class UnitTotals:
    """Итог одной пиццерии: подразделение iSpring, её страна и связь с рейтингами."""

    department_id: str
    title: str
    country_code: str
    matched: bool
    counters: Counters


@dataclass(frozen=True)
class CourseTotals:
    course_id: str
    title: str
    counters: Counters


#: Столбцы-вещественные; остальные счётчики целые (`sum` в базе отдаёт numeric — приводим).
_FLOAT_COLUMNS = frozenset({"score_sum", "days_sum"})


def _counters(values: Sequence[Any], columns: Sequence[str]) -> Counters:
    named: dict[str, Any] = {
        c: (float(v or 0) if c in _FLOAT_COLUMNS else int(v or 0))
        for c, v in zip(columns, values, strict=True)
    }
    return Counters(**named)


def _fail(what: str, exc: psycopg.Error) -> LearningError:
    return LearningError(
        f"Обучение не прочиталось ({what}): база отказала ({exc.__class__.__name__})"
    )


def snapshot_date() -> date | None:
    """Дата последнего снимка; `None` — загрузки ещё не было."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute("select max(sync_date) from learning.unit_totals").fetchone()
    except psycopg.Error as exc:
        raise _fail("дата снимка", exc) from exc
    return row[0] if row else None


def unit_totals(on_date: date, countries: Sequence[str] | None) -> tuple[UnitTotals, ...]:
    """Пиццерии снимка (сопоставленные и нет) в охвате `countries`."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                _UNITS_SQL,
                {"on_date": on_date, "countries": None if countries is None else list(countries)},
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("пиццерии", exc) from exc
    return tuple(
        UnitTotals(r[0], r[1], r[2], r[3] is not None, _counters(r[4:], COLUMNS)) for r in rows
    )


def course_totals(
    on_date: date,
    countries: Sequence[str] | None,
    *,
    country: str | None = None,
    department: str | None = None,
) -> tuple[CourseTotals, ...]:
    """Курсы в срезе: вся сеть в охвате, страна или одна пиццерия (по подразделению iSpring)."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(
                _COURSES_SQL,
                {
                    "on_date": on_date,
                    "countries": None if countries is None else list(countries),
                    "country": country,
                    "department": department,
                },
            ).fetchall()
    except psycopg.Error as exc:
        raise _fail("курсы", exc) from exc
    return tuple(CourseTotals(r[0], r[1], _counters(r[2:], COURSE_COLUMNS)) for r in rows)
