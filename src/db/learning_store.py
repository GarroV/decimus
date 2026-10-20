"""Обучение в базе (схема `learning`, миграция 0085): запись снимка дня и журнал загрузок.

Только агрегаты (D575): подразделение, курс, счётчики. Снимок дня заменяется целиком —
повторная загрузка того же дня не оставляет ни задвоенных строк, ни строк исчезнувших
подразделений. Чтение для экрана — `training_read.py`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime

import psycopg

from src.domain.training_metrics import COLUMNS, Counters

from .config import check_environment
from .errors import LearningError
from .pool import connection
from .training_names import COURSE_COLUMNS

_TOTALS_SQL = (
    f"insert into learning.unit_totals (sync_date, department_id, {', '.join(COLUMNS)}) "  # noqa: S608
    f"values (%s, %s, {', '.join(['%s'] * len(COLUMNS))})"
)
_COURSES_SQL = (
    f"insert into learning.unit_courses (sync_date, department_id, course_id, "  # noqa: S608
    f"{', '.join(COURSE_COLUMNS)}) values (%s, %s, %s, {', '.join(['%s'] * len(COURSE_COLUMNS))})"
)
_DEPARTMENT_SQL = """
insert into learning.departments (ispring_id, title, kind, country_code, parent_id,
                                  unit_dodo_id, seen_at)
values (%s, %s, %s, %s, %s, %s, now())
on conflict (ispring_id) do update set
    title = excluded.title, kind = excluded.kind, country_code = excluded.country_code,
    parent_id = excluded.parent_id, unit_dodo_id = excluded.unit_dodo_id, seen_at = now()
"""
_COURSE_SQL = """
insert into learning.courses (course_id, title, seen_at) values (%s, %s, now())
on conflict (course_id) do update set title = excluded.title, seen_at = now()
"""


def _values(counters: Counters, columns: Sequence[str]) -> tuple[float, ...]:
    return tuple(getattr(counters, c) for c in columns)


def known_units() -> list[tuple[str, str, str | None]]:
    """Пиццерии рейтингов — то, с чем сопоставляются подразделения iSpring."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute("select dodo_id, name, country_code from ratings.units").fetchall()
    except psycopg.Error as exc:
        raise LearningError(
            f"Пиццерии рейтингов не прочитались ({exc.__class__.__name__})"
        ) from exc
    return [(r[0], r[1], r[2]) for r in rows]


def save_snapshot(
    on_date: date,
    departments: Sequence[tuple[str, str, str, str | None, str | None, str | None]],
    totals: Mapping[str, Counters],
    courses: Mapping[tuple[str, str], Counters],
    titles: Mapping[str, str],
) -> None:
    """Подразделения, названия курсов и снимок дня — одной транзакцией.

    `departments` — (id, название, вид, страна, родитель, пиццерия рейтингов).
    """
    try:
        with connection(check_environment().dsn) as conn, conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(_DEPARTMENT_SQL, departments)
                cur.executemany(_COURSE_SQL, list(titles.items()))
                cur.execute("delete from learning.unit_totals where sync_date = %s", (on_date,))
                cur.execute("delete from learning.unit_courses where sync_date = %s", (on_date,))
                cur.executemany(
                    _TOTALS_SQL,
                    [(on_date, d, *_values(c, COLUMNS)) for d, c in totals.items()],
                )
                cur.executemany(
                    _COURSES_SQL,
                    [(on_date, d, k, *_values(c, COURSE_COLUMNS)) for (d, k), c in courses.items()],
                )
    except psycopg.Error as exc:
        raise LearningError(f"Обучение не легло: база отказала ({exc.__class__.__name__})") from exc


def log_load(*, ok: bool, departments: int = 0, results: int = 0, error: str | None = None) -> None:
    """След загрузки в журнале. Отказ журнала — `LearningError`, загрузку он не отменяет."""
    try:
        with connection(check_environment().dsn) as conn:
            conn.execute(
                "insert into learning.loads (outcome, departments, results, error) "
                "values (%s, %s, %s, %s)",
                ("ok" if ok else "failed", departments, results, (error or "")[:500] or None),
            )
    except psycopg.Error as exc:
        raise LearningError(
            f"Журнал загрузок обучения не записался ({exc.__class__.__name__})"
        ) from exc


def last_ok_load() -> datetime | None:
    """Когда последний раз загрузка удалась (`None` — ни разу)."""
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute("select max(at) from learning.loads where outcome = 'ok'").fetchone()
    except psycopg.Error as exc:
        raise LearningError(
            f"Журнал загрузок обучения не прочитался ({exc.__class__.__name__})"
        ) from exc
    return row[0] if row else None
