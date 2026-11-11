"""D746: actual source-period identity wins over checkup calendar dates."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest
from conftest import requires_db

from src.db import ratings_read as read

pytestmark = requires_db
UNIT = "a" * 32
AUGUST = "b" * 32
SEPTEMBER = "c" * 32
UNKNOWN = "d" * 32


@pytest.fixture
def period_data(db_env: str) -> tuple[str, dict[str, int], int]:
    with psycopg.connect(db_env) as conn:
        imp = conn.execute(
            "insert into ratings.imports (actor,channel,format,sha256,outcome,accepted) "
            "values ('d746-test','web','snapshot',%s,'loaded',1) returning id",
            ("a" * 64,),
        ).fetchone()[0]
        conn.execute(
            "insert into ratings.countries(code,name_ru,name_en) "
            "values ('ZZ','Synthetic','Synthetic') on conflict do nothing"
        )
        conn.execute(
            "insert into ratings.units(dodo_id,name,name_normalized,country_code) "
            "values (%s,'Synthetic-1','synthetic-1','ZZ')",
            (UNIT,),
        )
        periods = {}
        for kind, source, begin, end in (
            ("rs", AUGUST, "2026-08-16", "2026-08-31"),
            ("rs", SEPTEMBER, "2026-09-01", "2026-09-15"),
            ("rko", "e" * 32, "2026-08-31", "2026-09-06"),
        ):
            periods[source] = conn.execute(
                "insert into ratings.periods"
                "(rating_type,dodo_id,begin_on,end_on,title_ru,title_en) "
                "values (%s,%s,%s,%s,'Synthetic','Synthetic') returning id",
                (kind, source, begin, end),
            ).fetchone()[0]
            conn.execute(
                "insert into ratings.scores(unit_dodo_id,period_id,score,source,import_id) "
                "values (%s,%s,90,'snapshot',%s)",
                (UNIT, periods[source], imp),
            )
    return db_env, periods, imp


def checkup(
    dsn: str, imp: int, index: int, when: str, source: str | None, kind="rs", period_id=None
):
    ident = f"{index:032x}"
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "insert into ratings.checkups(rating_type,dodo_id,unit_dodo_id,occurred_at,"
            "period_dodo_id,acceptance,import_id) values (%s,%s,%s,%s,%s,'accepted',%s)",
            (kind, ident, UNIT, when, source, imp),
        )
        conn.execute(
            "insert into ratings.violations(row_key,rating_type,checkup_dodo_id,unit_dodo_id,"
            "text,category,import_id,period_id) "
            "values (%s,%s,%s,%s,'Synthetic issue','violation',%s,%s)",
            (f"synthetic-{index}", kind, ident, UNIT, imp, period_id),
        )
    return ident


def test_rs_source_period_overrides_cross_month_occurrence_and_unknown_is_not_guessed(period_data):
    dsn, periods, imp = period_data
    checkup(dsn, imp, 1, "2026-09-01 12:00+00", AUGUST)
    checkup(dsn, imp, 2, "2026-09-05 12:00+00", SEPTEMBER)
    checkup(dsn, imp, 3, "2026-09-05 12:00+00", None)
    checkup(dsn, imp, 4, "2026-09-05 12:00+00", UNKNOWN)
    rows = read.unit_periods(UNIT, rating_type="rs", begin=date(2026, 8, 1), end=date(2026, 9, 30))
    actual = {r.period_id: (r.loaded_checkups, r.accepted_checkups, r.violations) for r in rows}
    assert actual == {periods[AUGUST]: (1, 1, 1), periods[SEPTEMBER]: (2, 2, 2)}


def test_rs_explicit_violation_period_does_not_duplicate_into_checkup_period(period_data):
    dsn, periods, imp = period_data
    checkup(dsn, imp, 1, "2026-09-05 12:00+00", SEPTEMBER, period_id=periods[AUGUST])
    rows = read.unit_periods(UNIT, rating_type="rs", begin=date(2026, 8, 1), end=date(2026, 9, 30))
    assert {r.period_id: r.violations for r in rows} == {periods[AUGUST]: 1, periods[SEPTEMBER]: 0}


def test_rko_week_keeps_date_membership_even_when_source_period_differs(period_data):
    dsn, _, imp = period_data
    checkup(dsn, imp, 1, "2026-09-01 12:00+00", UNKNOWN, kind="rko")
    rows = read.unit_periods(UNIT, rating_type="rko", begin=date(2026, 9, 1), end=date(2026, 9, 30))
    assert len(rows) == 1
    assert (rows[0].loaded_checkups, rows[0].accepted_checkups, rows[0].violations) == (1, 1, 1)


def test_source_api_windows_use_country_scope_actual_dates_and_checkup_count(period_data):
    dsn, _, _ = period_data
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "insert into ratings.countries(code,name_ru,name_en) values ('YY','Other','Other') "
            "on conflict do nothing"
        )
        conn.execute(
            "insert into ratings.units(dodo_id,name,name_normalized,country_code) "
            "values (%s,'Other-1','other-1','YY')",
            ("f" * 32,),
        )
        for unit, rate in ((UNIT, 88), ("f" * 32, 99)):
            conn.execute(
                "insert into dodois.unit_rating_period"
                "(dodo_id,kind,period_from,period_to,rate,publish_status) "
                "values (%s,'rs','2026-08-31','2026-09-13',%s,'Published')",
                (unit, rate),
            )
        conn.execute(
            "insert into dodois.unit_checkup_period"
            "(dodo_id,kind,period_from,period_to,checkups) "
            "values (%s,'rs','2026-08-31','2026-09-13',2)",
            (UNIT,),
        )
    rows = read.source_rating_periods(
        countries=("ZZ",), rating_type="rs", begin=date(2026, 9, 1), end=date(2026, 9, 30)
    )
    assert rows == (
        read.SourceRatingPeriod(
            UNIT,
            "Synthetic-1",
            "ZZ",
            "rs",
            date(2026, 8, 31),
            date(2026, 9, 13),
            88,
            "Published",
            2,
        ),
    )
    assert not read.source_rating_periods(
        countries=("YY",), rating_type="rko", begin=date(2026, 9, 1), end=date(2026, 9, 30)
    )
