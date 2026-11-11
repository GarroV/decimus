"""D746 source-period priority and scoped source links on actual PostgreSQL."""

from __future__ import annotations

import psycopg
import pytest
from conftest import requires_db

from src.db import ratings_violations as read
from src.ratings import violations_view as view
from src.ratings.periods import KIND_RATING, ReportPeriod, month_period

pytestmark = requires_db
UNIT = "a" * 32
SEPTEMBER, OCTOBER, WEEK, UNKNOWN = (c * 32 for c in "bcde")


@pytest.fixture
def violations_data(db_env: str):
    with psycopg.connect(db_env) as conn:
        imp = conn.execute(
            "insert into ratings.imports(actor,channel,format,sha256,outcome,accepted) "
            "values ('d746-view','web','snapshot',%s,'loaded',1) returning id",
            ("f" * 64,),
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
            ("rs", SEPTEMBER, "2026-09-16", "2026-09-30"),
            ("rs", OCTOBER, "2026-10-01", "2026-10-15"),
            ("rko", WEEK, "2026-09-28", "2026-10-04"),
        ):
            periods[source] = conn.execute(
                "insert into ratings.periods(rating_type,dodo_id,begin_on,end_on,"
                "title_ru,title_en) "
                "values (%s,%s,%s,%s,'Synthetic','Synthetic') returning id",
                (kind, source, begin, end),
            ).fetchone()[0]
        for n, kind, source, when, acceptance in (
            ("1", "rs", SEPTEMBER, "2026-10-01", None),
            ("2", "rs", OCTOBER, "2026-09-30", None),
            ("3", "rs", UNKNOWN, "2026-10-01", None),
            ("4", "rs", None, "2026-10-02", None),
            ("5", "rko", WEEK, "2026-09-30", None),
            ("6", "rko", WEEK, "2026-10-01", "rejected"),
            ("7", "rko", WEEK, "2026-10-01", None),
        ):
            conn.execute(
                "insert into ratings.checkups(rating_type,dodo_id,unit_dodo_id,country_code,"
                "occurred_at,period_dodo_id,acceptance,import_id) "
                "values(%s,%s,%s,'ZZ',%s::date::timestamp at time zone 'UTC',%s,%s,%s)",
                (kind, n * 32, UNIT, when, source, acceptance, imp),
            )
            conn.execute(
                "insert into ratings.violations(row_key,rating_type,checkup_dodo_id,unit_dodo_id,"
                "text,category,criterion_id,amount,import_id) "
                "values(%s,%s,%s,%s,%s,'violation',%s,1,%s)",
                ("check-" + n, kind, n * 32, UNIT, "Synthetic " + n, "C" + n, imp),
            )
        conn.execute(
            "insert into ratings.violations(row_key,rating_type,checkup_dodo_id,unit_dodo_id,"
            "period_id,text,category,criterion_id,amount,import_id) "
            "values('explicit-v-period','rs',%s,%s,%s,'Explicit period','violation','VP',2,%s)",
            ("1" * 32, UNIT, periods[OCTOBER], imp),
        )
        conn.execute(
            "insert into ratings.violations(row_key,rating_type,unit_dodo_id,period_id,"
            "text,category,criterion_id,amount,import_id) "
            "values('week-remark','rko',%s,%s,'Week remark','remark','RW',3,%s)",
            (UNIT, periods[WEEK], imp),
        )
    return periods


def facts(kind, countries, period):
    return read.facts(kind, countries, view._window(kind, period))


def checkup_coverage(kind, countries, period):
    return read.checkup_coverage(kind, countries, view._window(kind, period))


def ids(rows):
    return {row.criterion_id for row in rows}


def test_rs_source_identity_wins_over_check_date_and_explicit_violation_period_wins(
    violations_data,
):
    september = facts("rs", ("ZZ",), month_period(2026, 9))
    october = facts("rs", ("ZZ",), month_period(2026, 10))
    assert ids(september) == {"C1"}
    assert ids(october) == {"C2", "C4", "VP"}
    period = ReportPeriod(
        KIND_RATING,
        f"rs:{violations_data[SEPTEMBER]}",
        month_period(2026, 9).begin,
        month_period(2026, 9).end,
    )
    assert ids(facts("rs", ("ZZ",), period)) == {"C1"}
    assert "C3" not in ids(october)  # an unknown explicit id never falls back to dates
    result = view.build("rs", ("ZZ",), month_period(2026, 10))
    chosen = next(row for row in result.rows if row.criterion_id == "VP")
    detail = view.build("rs", ("ZZ",), month_period(2026, 10), criterion=chosen.key).selected
    assert detail is not None
    # The occurrence can belong to an explicit export period, while the link
    # must keep the source checkup's own period rather than inventing another.
    assert "ratingPeriodId=" + SEPTEMBER in detail.units[0].checks[0].url


def test_rko_rejected_is_outside_date_scope_but_week_remark_overlaps_both_months(
    violations_data,
):
    assert ids(facts("rko", ("ZZ",), month_period(2026, 9))) == {"C5", "RW"}
    assert ids(facts("rko", ("ZZ",), month_period(2026, 10))) == {"C7", "RW"}


def test_empty_country_scope_never_reads_other_units_and_detail_has_no_photos(violations_data):
    period = month_period(2026, 10)
    assert facts("rs", (), period) == ()
    assert facts("rs", ("ZY",), period) == ()
    result = view.build("rs", ("ZZ",), period)
    selected = view.build("rs", ("ZZ",), period, criterion=result.rows[0].key)
    assert result.total_cases == 4 and result.units == 1
    assert selected.selected is not None
    assert selected.selected.photos_available is False
    assert selected.selected.units[0].checks[0].url.startswith("https://knowledgebase.dodois.io/")


def test_rko_can_use_the_shared_rs_period_filter_as_a_date_frame(violations_data):
    frame = month_period(2026, 10)
    period = ReportPeriod(KIND_RATING, f"rs:{violations_data[OCTOBER]}", frame.begin, frame.end)
    assert ids(facts("rko", ("ZZ",), period)) == {"C7", "RW"}


def test_metadata_coverage_is_scoped_and_does_not_multiply_violation_rows(violations_data):
    period = month_period(2026, 10)
    result = view.build("rs", ("ZZ",), period)
    assert result.observed_checkups == 2
    assert result.coverage == "violations"
    assert result.checkups_loaded_at is not None
    assert checkup_coverage("rs", (), period).count == 0
    assert checkup_coverage("rs", ("ZY",), period).loaded_at is None


def test_checkup_from_another_unit_is_not_a_proof_for_scoped_violation(
    violations_data, db_env: str
):
    with psycopg.connect(db_env) as conn:
        conn.execute(
            "insert into ratings.units(dodo_id,name,name_normalized,country_code) "
            "values (%s,'Synthetic-2','synthetic-2','ZZ')",
            ("9" * 32,),
        )
        conn.execute(
            "update ratings.checkups set unit_dodo_id=%s where dodo_id=%s and rating_type='rs'",
            ("9" * 32, "2" * 32),
        )
    assert "C2" not in ids(facts("rs", ("ZZ",), month_period(2026, 10)))
