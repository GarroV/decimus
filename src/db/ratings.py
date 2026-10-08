"""Запись рейтингов РС/РКО: журнал загрузок и строки схемы `ratings` (0038).

Всё, кроме `record_failure`, работает внутри соединения, которое держит дверь
загрузки (`src/ratings/importer.py`): одна транзакция на файл. Повтор строки по
ключу обновляет её — `on conflict … do update`; что было вставлено, а что
обновлено, отвечает `xmax = 0` из `returning`.

Журнал `ratings.imports` роль приложения только дописывает: исход, автор, sha и
причина задаются при вставке, позже меняются лишь счётчики (грант 0038).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .config import check_environment

INSERTED = "inserted"
UPDATED = "updated"
KEPT = "kept"

OUTCOME_FAILED = "failed"

#: Пределы колонок журнала (CHECK 0038).
MAX_FILE_NAME = 255
MAX_NOTE = 2000
MAX_DEVELOPER = 120
MAX_UNIT_NAME = 120
MAX_VIOLATION_TEXT = 500


@dataclass(frozen=True)
class ViolationRow:
    row_key: str
    text: str
    category: str
    auto_detected: bool
    criterion_id: str | None
    parent_name: str | None
    deduction: float | None
    amount: int


def _outcome(row: tuple[Any, ...] | None) -> str:
    if row is None:
        return KEPT
    return INSERTED if row[0] else UPDATED


def lock_imports(conn: psycopg.Connection) -> None:
    """Загрузки идут по одной: два одинаковых файла разом не лягут оба."""
    conn.execute("select pg_advisory_xact_lock(hashtext('ratings.imports'))")


def loaded_with(conn: psycopg.Connection, sha: str) -> tuple[int, datetime] | None:
    row = conn.execute(
        "select id, at from ratings.imports where sha256 = %s and outcome = 'loaded'", (sha,)
    ).fetchone()
    return None if row is None else (int(row[0]), row[1])


def open_import(
    conn: psycopg.Connection,
    *,
    channel: str,
    actor: str,
    fmt: str | None,
    file_name: str | None,
    sha: str,
    outcome: str,
    duplicate_of: int | None = None,
    note: str | None = None,
) -> int:
    row = conn.execute(
        "insert into ratings.imports "
        "(channel, actor, format, file_name, sha256, outcome, duplicate_of, note) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (
            channel,
            actor,
            fmt,
            file_name[:MAX_FILE_NAME] if file_name else None,
            sha,
            outcome,
            duplicate_of,
            None if note is None else note[:MAX_NOTE],
        ),
    ).fetchone()
    assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
    return int(row[0])


def close_import(
    conn: psycopg.Connection,
    import_id: int,
    *,
    accepted: int,
    updated: int,
    skipped: int,
    unmatched: int,
) -> None:
    conn.execute(
        "update ratings.imports set accepted = %s, updated = %s, skipped = %s, unmatched = %s "
        "where id = %s",
        (accepted, updated, skipped, unmatched, import_id),
    )


def add_issues(
    conn: psycopg.Connection, import_id: int, issues: Sequence[tuple[int, str, Mapping[str, str]]]
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "insert into ratings.import_issues (import_id, row_no, reason, detail) "
            "values (%s, %s, %s, %s) on conflict do nothing",
            [(import_id, row_no, reason, Jsonb(dict(detail))) for row_no, reason, detail in issues],
        )


def record_failure(
    *, channel: str, actor: str, file_name: str | None, sha: str, note: str, fmt: str | None = None
) -> int:
    """След неудачной загрузки — своей транзакцией: основная уже откатилась."""
    with psycopg.connect(check_environment().dsn) as conn:
        return open_import(
            conn,
            channel=channel,
            actor=actor,
            fmt=fmt,
            file_name=file_name,
            sha=sha,
            outcome=OUTCOME_FAILED,
            note=note,
        )


def known_units(conn: psycopg.Connection) -> list[tuple[str, str, str | None]]:
    return [
        (r[0], r[1], r[2])
        for r in conn.execute("select dodo_id, name, country_code from ratings.units").fetchall()
    ]


def ensure_country(
    conn: psycopg.Connection,
    code: str,
    *,
    name_ru: str,
    name_en: str,
    is_imf: bool,
    dodo_id: int | None = None,
) -> None:
    conn.execute(
        "insert into ratings.countries (code, name_ru, name_en, is_imf, dodo_id) "
        "values (%s, %s, %s, %s, %s) "
        "on conflict (code) do update set "
        "  dodo_id = coalesce(ratings.countries.dodo_id, excluded.dodo_id)",
        (code, name_ru, name_en, is_imf, dodo_id),
    )


def set_developer_if_empty(conn: psycopg.Connection, code: str, developer: str) -> None:
    conn.execute(
        "update ratings.countries set developer = %s, updated_by = 'import', updated_at = now() "
        "where code = %s and developer is null",
        (developer.strip()[:MAX_DEVELOPER], code),
    )


def upsert_unit(
    conn: psycopg.Connection, dodo_id: str, *, name: str, name_normalized: str, country: str | None
) -> None:
    conn.execute(
        "insert into ratings.units (dodo_id, name, name_normalized, country_code) "
        "values (%s, %s, %s, %s) "
        "on conflict (dodo_id) do update set name = excluded.name, "
        "  name_normalized = excluded.name_normalized, "
        "  country_code = coalesce(excluded.country_code, ratings.units.country_code), "
        "  updated_at = now()",
        (dodo_id, name[:MAX_UNIT_NAME], name_normalized, country),
    )


def upsert_period(
    conn: psycopg.Connection,
    *,
    rating_type: str,
    begin_on: date,
    end_on: date,
    title_ru: str,
    title_en: str,
    dodo_id: str | None,
) -> int:
    """Период по типу и дате начала. Описание из снимка (с id Dodo IS) главнее листа."""
    row = conn.execute(
        "insert into ratings.periods (rating_type, dodo_id, begin_on, end_on, title_ru, title_en) "
        "values (%s, %s, %s, %s, %s, %s) "
        "on conflict (rating_type, begin_on) do update set "
        "  dodo_id = coalesce(ratings.periods.dodo_id, excluded.dodo_id), "
        "  end_on = case when excluded.dodo_id is null "
        "    then ratings.periods.end_on else excluded.end_on end, "
        "  title_ru = case when excluded.dodo_id is null "
        "    then ratings.periods.title_ru else excluded.title_ru end, "
        "  title_en = case when excluded.dodo_id is null "
        "    then ratings.periods.title_en else excluded.title_en end "
        "returning id",
        (rating_type, dodo_id, begin_on, end_on, title_ru, title_en),
    ).fetchone()
    assert row is not None  # noqa: S101 — insert ... returning без строки не бывает
    return int(row[0])


def upsert_score(
    conn: psycopg.Connection,
    *,
    unit: str,
    period_id: int,
    score: float,
    status: str | None,
    checkups_count: int | None,
    source: str,
    import_id: int,
) -> str:
    """Балл пиццерии за период. Лист не перезаписывает балл снимка."""
    return _outcome(
        conn.execute(
            "insert into ratings.scores "
            "(unit_dodo_id, period_id, score, status, checkups_count, source, import_id) "
            "values (%s, %s, %s, %s, %s, %s, %s) "
            "on conflict (unit_dodo_id, period_id) do update set score = excluded.score, "
            "  status = excluded.status, "
            "  checkups_count = coalesce(excluded.checkups_count, ratings.scores.checkups_count), "
            "  source = excluded.source, import_id = excluded.import_id, updated_at = now() "
            "where not (ratings.scores.source = 'snapshot' and excluded.source = 'sheet') "
            "returning (xmax = 0)",
            (unit, period_id, score, status, checkups_count, source, import_id),
        ).fetchone()
    )


def upsert_checkup(
    conn: psycopg.Connection,
    *,
    rating_type: str,
    dodo_id: str,
    unit: str,
    country: str | None,
    occurred_at: datetime | None,
    channel: str,
    period_dodo_id: str | None,
    backoffice_url: str,
    rating_url: str,
    duration_min: int | None,
    import_id: int,
) -> str:
    return _outcome(
        conn.execute(
            "insert into ratings.checkups (rating_type, dodo_id, unit_dodo_id, country_code, "
            "  occurred_at, channel, period_dodo_id, backoffice_url, rating_url, duration_min, "
            "  import_id) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (rating_type, dodo_id) do update set "
            "  unit_dodo_id = excluded.unit_dodo_id, country_code = excluded.country_code, "
            "  occurred_at = excluded.occurred_at, channel = excluded.channel, "
            "  period_dodo_id = excluded.period_dodo_id, backoffice_url = excluded.backoffice_url, "
            "  rating_url = excluded.rating_url, duration_min = excluded.duration_min "
            "returning (xmax = 0)",
            (
                rating_type,
                dodo_id,
                unit,
                country,
                occurred_at,
                channel,
                period_dodo_id,
                backoffice_url,
                rating_url,
                duration_min,
                import_id,
            ),
        ).fetchone()
    )


def set_acceptance(
    conn: psycopg.Connection,
    *,
    dodo_id: str,
    country: str,
    acceptance: str,
    evaluated_at: datetime | None,
    import_id: int,
) -> str:
    """Приёмка фото РКО. Проверку может ещё не знать никто — строка заводится без пиццерии."""
    return _outcome(
        conn.execute(
            "insert into ratings.checkups "
            "(rating_type, dodo_id, country_code, acceptance, evaluated_at, import_id) "
            "values ('rko', %s, %s, %s, %s, %s) "
            "on conflict (rating_type, dodo_id) do update set acceptance = excluded.acceptance, "
            "  evaluated_at = excluded.evaluated_at, "
            "  country_code = coalesce(ratings.checkups.country_code, excluded.country_code) "
            "returning (xmax = 0)",
            (dodo_id, country, acceptance, evaluated_at, import_id),
        ).fetchone()
    )


_INSERT_VIOLATION = (
    "insert into ratings.violations (row_key, rating_type, checkup_dodo_id, unit_dodo_id, "
    "  period_id, text, category, criterion_id, parent_name, auto_detected, deduction, amount, "
    "  import_id) "
    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def _insert(
    conn: psycopg.Connection,
    rows: Sequence[ViolationRow],
    *,
    rating_type: str,
    checkup: str | None,
    unit: str,
    period_id: int | None,
    import_id: int,
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            _INSERT_VIOLATION,
            [
                (
                    r.row_key,
                    rating_type,
                    checkup,
                    unit,
                    period_id,
                    r.text[:MAX_VIOLATION_TEXT],
                    r.category,
                    r.criterion_id,
                    r.parent_name,
                    r.auto_detected,
                    r.deduction,
                    r.amount,
                    import_id,
                )
                for r in rows
            ],
        )


def replace_checkup_violations(
    conn: psycopg.Connection,
    *,
    rating_type: str,
    checkup: str,
    unit: str,
    rows: Sequence[ViolationRow],
    import_id: int,
) -> None:
    """Нарушения проверки — набором: новый файл о той же проверке заменяет прежний набор."""
    conn.execute(
        "delete from ratings.violations where rating_type = %s and checkup_dodo_id = %s",
        (rating_type, checkup),
    )
    _insert(
        conn,
        rows,
        rating_type=rating_type,
        checkup=checkup,
        unit=unit,
        period_id=None,
        import_id=import_id,
    )


def replace_remarks(
    conn: psycopg.Connection,
    *,
    unit: str,
    period_id: int,
    rows: Sequence[ViolationRow],
    import_id: int,
) -> None:
    """Замечания периода РС (снимок) — набором по пиццерии и периоду."""
    conn.execute(
        "delete from ratings.violations "
        "where category = 'remark' and unit_dodo_id = %s and period_id = %s",
        (unit, period_id),
    )
    _insert(
        conn,
        rows,
        rating_type="rs",
        checkup=None,
        unit=unit,
        period_id=period_id,
        import_id=import_id,
    )
