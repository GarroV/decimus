"""Запись рейтингов РС/РКО: журнал загрузок и строки схемы `ratings` (0039).

Всё, кроме `record_failure`, работает внутри соединения, которое держит дверь
загрузки (`src/ratings/importer.py`): одна транзакция на файл. Повтор строки по
ключу обновляет её — `on conflict … do update`; что было вставлено, а что
обновлено, отвечает `xmax = 0` из `returning`.

Журнал `ratings.imports` роль приложения только дописывает: исход, автор, sha и
причина задаются при вставке, позже меняются лишь счётчики (грант 0039).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .config import check_environment
from .errors import RatingsError
from .pool import connection

INSERTED = "inserted"
UPDATED = "updated"
KEPT = "kept"

OUTCOME_FAILED = "failed"

#: Пределы колонок журнала (CHECK 0039).
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
    with connection(check_environment().dsn) as conn:
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


# Живая точка — та, у которой есть оценка РС или РКО за период, кончившийся не
# раньше `since` (D556): рейтинги считает Dodo IS, и закрытая пиццерия из них
# выпадает сама.
_LIVE_UNITS_SQL = """
select u.dodo_id, u.name, u.country_code
  from ratings.units u
 where u.country_code is not null
   and exists (
       select 1
         from ratings.scores s
         join ratings.periods p on p.id = s.period_id
        where s.unit_dodo_id = u.dodo_id and p.end_on >= %(since)s)
 order by u.country_code, u.name
"""


def live_units(since: date) -> list[tuple[str, str, str]]:
    """Точки рейтингов с оценкой за период, кончившийся не раньше `since`: код, имя, страна."""
    try:
        with connection(check_environment().dsn) as conn:
            rows = conn.execute(_LIVE_UNITS_SQL, {"since": since}).fetchall()
    except psycopg.Error as exc:
        raise RatingsError(f"Точки рейтингов недоступны ({type(exc).__name__}): {exc}") from exc
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


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
    """Период по типу и дате начала. Описание из снимка (с id Dodo IS) главнее листа.

    Слот (тип, начало) уже занят периодом с ДРУГИМ id Dodo IS — `RatingsError`, а
    не склейка: иначе баллы нового периода молча легли бы на старый. Так же, как
    тот же id с другим началом (там отказывает уникальный индекс `dodo_id`).
    """
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
        "where ratings.periods.dodo_id is null or excluded.dodo_id is null "
        "  or ratings.periods.dodo_id = excluded.dodo_id "
        "returning id",
        (rating_type, dodo_id, begin_on, end_on, title_ru, title_en),
    ).fetchone()
    if row is None:
        raise RatingsError(
            f"Период {rating_type} с началом {begin_on:%d.%m.%Y} уже загружен с другим id "
            f"Dodo IS, файл несёт {dodo_id}. Ничего не записано"
        )
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


def upsert_base_score(
    conn: psycopg.Connection,
    *,
    unit: str,
    period_id: int,
    score: float,
    flags: tuple[bool, str | None, bool, str | None, bool, str | None],
    import_id: int,
) -> str:
    """Оценка из листа «база рейтингов» с флагами Д3, критичное, обнуление (D464).

    Строка, где всё то же, не трогается (`kept`): повтор листа не двигает ни
    `updated_at`, ни счётчики. Балл снимка листом не перезаписывается, как у
    `upsert_score`.
    """
    return _outcome(
        conn.execute(
            "insert into ratings.scores (unit_dodo_id, period_id, score, source, import_id, "
            "  d3, d3_name, critical, critical_name, zeroing, zeroing_name) "
            "values (%s, %s, %s, 'sheet', %s, %s, %s, %s, %s, %s, %s) "
            "on conflict (unit_dodo_id, period_id) do update set score = excluded.score, "
            "  source = 'sheet', import_id = excluded.import_id, updated_at = now(), "
            "  d3 = excluded.d3, d3_name = excluded.d3_name, critical = excluded.critical, "
            "  critical_name = excluded.critical_name, zeroing = excluded.zeroing, "
            "  zeroing_name = excluded.zeroing_name "
            "where ratings.scores.source <> 'snapshot' "
            "  and (ratings.scores.score, ratings.scores.d3, ratings.scores.d3_name, "
            "    ratings.scores.critical, ratings.scores.critical_name, ratings.scores.zeroing, "
            "    ratings.scores.zeroing_name) "
            "  is distinct from (excluded.score, excluded.d3, excluded.d3_name, "
            "    excluded.critical, excluded.critical_name, excluded.zeroing, "
            "    excluded.zeroing_name) "
            "returning (xmax = 0)",
            (unit, period_id, score, import_id, *flags),
        ).fetchone()
    )


def upsert_collection(
    conn: psycopg.Connection,
    *,
    unit: str,
    period_id: int,
    restaurant: int,
    delivery: int,
    import_id: int,
) -> str:
    """Отчёты РКО пиццерии за неделю; те же числа — `kept`."""
    return _outcome(
        conn.execute(
            "insert into ratings.collection "
            "(unit_dodo_id, period_id, restaurant_reports, delivery_reports, import_id) "
            "values (%s, %s, %s, %s, %s) "
            "on conflict (unit_dodo_id, period_id) do update set "
            "  restaurant_reports = excluded.restaurant_reports, "
            "  delivery_reports = excluded.delivery_reports, "
            "  import_id = excluded.import_id, updated_at = now() "
            "where (ratings.collection.restaurant_reports, ratings.collection.delivery_reports) "
            "  is distinct from (excluded.restaurant_reports, excluded.delivery_reports) "
            "returning (xmax = 0)",
            (unit, period_id, restaurant, delivery, import_id),
        ).fetchone()
    )


#: Нарушения листов «базы рейтингов» узнаются по префиксу ключа: набор пиццерии
#: и периода заменяется целиком, замечания снимка (`replace_remarks`) не трогаются.
SHEET_REMARK_PREFIX = "sheet:"


def replace_sheet_remarks(
    conn: psycopg.Connection,
    *,
    rating_type: str,
    unit: str,
    period_id: int,
    rows: Sequence[ViolationRow],
    import_id: int,
) -> str:
    """Нарушения пиццерии за период из листа — набором. Тот же набор — `kept`."""
    existing = {
        str(r[0]): int(r[1])
        for r in conn.execute(
            "select row_key, amount from ratings.violations "
            "where category = 'remark' and unit_dodo_id = %s and period_id = %s "
            "and row_key like %s",
            (unit, period_id, SHEET_REMARK_PREFIX + "%"),
        ).fetchall()
    }
    if existing == {r.row_key: r.amount for r in rows}:
        return KEPT
    conn.execute(
        "delete from ratings.violations "
        "where category = 'remark' and unit_dodo_id = %s and period_id = %s "
        "and row_key like %s",
        (unit, period_id, SHEET_REMARK_PREFIX + "%"),
    )
    _insert(
        conn,
        rows,
        rating_type=rating_type,
        checkup=None,
        unit=unit,
        period_id=period_id,
        import_id=import_id,
    )
    return UPDATED if existing else INSERTED
