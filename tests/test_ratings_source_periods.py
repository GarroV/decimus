"""D746 source facts: true dates, accepted month ownership, explicit fallback."""

from __future__ import annotations

from datetime import date

import pytest

from src.db import ratings_read as read
from src.ratings import source_periods as source
from src.ratings.periods import KIND_RANGE, ReportPeriod, month_period, quarter_period
from src.ratings.summary import group_average

A = "a" * 32
B = "b" * 32
TODAY = date(2026, 10, 10)


def api(unit, begin, end, score, *, country="RS", kind="rs", checkups=None, status="Published"):
    return read.SourceRatingPeriod(
        unit,
        f"Synthetic-{unit[0]}",
        country,
        kind,
        date.fromisoformat(begin),
        date.fromisoformat(end),
        score,
        status,
        checkups,
    )


def legacy(unit, score, *, kind="rs", country="RS", begin=date(2026, 9, 1), end=date(2026, 9, 15)):
    return (unit, f"Synthetic-{unit[0]}", country, kind, 1, begin, score, end)


def stub(monkeypatch, rows=(), old=()):
    monkeypatch.setattr(read, "source_rating_periods", lambda **kw: rows)
    monkeypatch.setattr(read, "score_facts", lambda **kw: old)


def test_rs_actual_dates_and_per_unit_fallback_match_quality_without_pooling_periods(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-08-31", "2026-09-13", 80, checkups=2),
            api(A, "2026-09-14", "2026-10-04", 100, checkups=3),
        ),
        old=(legacy(A, 10), legacy(B, 50)),
    )
    view = source.load("rs", ("RS",), month_period(2026, 9), TODAY)
    assert [(t.begin_on.isoformat(), t.end_on.isoformat(), t.avg, t.units) for t in view.tiles] == [
        ("2026-08-31", "2026-09-13", 80, 1),
        ("2026-09-14", "2026-10-04", 100, 1),
    ]
    assert group_average(view.facts, "rs", ("RS",)) == 70
    assert (view.source, view.actual_dates) == ("mixed", False)
    assert all(t.source == "dodois" and t.actual_dates and t.period_id is None for t in view.tiles)
    assert [t.checkups for t in view.tiles] == [2, 3]
    assert all(t.publication_statuses == ("Published",) for t in view.tiles)
    assert all(f.period_id < 0 for f in view.facts if f.unit == A)
    assert [t.key for t in view.tiles] == ["2026-08-31..2026-09-13", "2026-09-14..2026-10-04"]


def test_rs_october_does_not_recount_september_period_touching_october(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-09-14", "2026-10-04", 100),
            api(A, "2026-09-28", "2026-10-11", 80),
        ),
    )
    view = source.load("rs", ("RS",), month_period(2026, 10), TODAY)
    assert [(t.begin_on, t.avg) for t in view.tiles] == [(date(2026, 9, 28), 80)]
    assert group_average(view.facts, "rs", ("RS",)) == 80


def test_rs_equal_cross_month_days_belong_to_start_month(monkeypatch):
    stub(monkeypatch, rows=(api(A, "2026-09-24", "2026-10-07", 70),))
    september = source.load("rs", ("RS",), month_period(2026, 9), TODAY)
    october = source.load("rs", ("RS",), month_period(2026, 10), TODAY)
    assert len(september.tiles) == 1 and not october.tiles


@pytest.mark.parametrize("month", [9, 10])
def test_rko_cross_month_week_has_its_result_in_both_month_views(monkeypatch, month):
    stub(monkeypatch, rows=(api(A, "2026-09-28", "2026-10-04", 81, kind="rko"),))
    view = source.load("rko", ("RS",), month_period(2026, month), TODAY)
    assert len(view.tiles) == 1
    assert (view.tiles[0].avg, view.tiles[0].units) == (81, 1)
    assert view.tiles[0].months == (date(2026, 9, 1), date(2026, 10, 1))
    assert (view.source, view.actual_dates) == ("dodois", True)


def test_sheet_only_does_not_invent_actual_calendar_cards(monkeypatch):
    stub(monkeypatch, old=(legacy(A, 90),))
    view = source.load("rs", ("RS",), month_period(2026, 9), TODAY)
    assert (view.tiles, view.source, view.actual_dates) == ((), "sheet", False)
    assert group_average(view.facts, "rs", ("RS",)) == 90


def test_future_source_window_is_visible_but_has_no_result_before_it_starts(monkeypatch):
    stub(monkeypatch, rows=(api(A, "2026-12-01", "2026-12-14", 99),))
    view = source.load("rs", ("RS",), quarter_period(2026, 4), TODAY)
    assert len(view.tiles) == 1
    tile = view.tiles[0]
    assert (tile.state, tile.avg, tile.units, view.facts) == ("upcoming", None, 0, ())
    assert (view.source, view.actual_dates) == ("dodois", True)


def test_scope_and_kind_are_applied_before_aggregating(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-09-01", "2026-09-14", 80),
            api(B, "2026-09-01", "2026-09-14", 10, country="BG"),
            api(B, "2026-09-01", "2026-09-14", 20, kind="rko"),
        ),
        old=(legacy(B, 10, country="BG"), legacy(B, 20, kind="rko")),
    )
    view = source.load("rs", ("RS",), month_period(2026, 9), TODAY)
    assert (view.tiles[0].avg, view.tiles[0].units) == (80, 1)
    assert all(f.country == "RS" and f.rating_type == "rs" for f in view.facts)


def test_empty_country_scope_does_not_read_other_countries(monkeypatch):
    def forbidden(**kw):
        raise AssertionError("empty scope must not query ratings")

    monkeypatch.setattr(read, "source_rating_periods", forbidden)
    monkeypatch.setattr(read, "score_facts", forbidden)
    assert source.load("rs", (), month_period(2026, 9), TODAY) == source.PeriodView(
        (), (), "", False
    )


def test_unknown_source_is_not_treated_as_a_known_rating(monkeypatch):
    stub(monkeypatch)
    with pytest.raises(ValueError, match="Unknown rating source"):
        source.load("not-a-rating", ("RS",), month_period(2026, 9), TODAY)


def test_previous_actual_rs_window_keeps_its_own_length_and_source_dates(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-08-31", "2026-09-13", 80),
            api(A, "2026-09-14", "2026-10-04", 90),
        ),
    )
    selected = ReportPeriod(
        KIND_RANGE, "2026-09-14..2026-10-04", date(2026, 9, 14), date(2026, 10, 4)
    )
    previous = source.previous_for("rs", ("RS",), selected, TODAY)
    assert previous == ReportPeriod(
        KIND_RANGE, "2026-08-31..2026-09-13", date(2026, 8, 31), date(2026, 9, 13)
    )


def test_previous_actual_rko_week_can_precede_an_ongoing_week(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-09-28", "2026-10-04", 80, kind="rko"),
            api(A, "2026-10-05", "2026-10-11", 90, kind="rko"),
        ),
    )
    selected = ReportPeriod(
        KIND_RANGE, "2026-10-05..2026-10-11", date(2026, 10, 5), date(2026, 10, 11)
    )
    assert source.previous_for("rko", ("RS",), selected, TODAY) == ReportPeriod(
        KIND_RANGE, "2026-09-28..2026-10-04", date(2026, 9, 28), date(2026, 10, 4)
    )


def test_previous_actual_window_is_unknown_for_different_unit_predecessors(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-08-31", "2026-09-13", 80),
            api(B, "2026-09-01", "2026-09-13", 81),
            api(A, "2026-09-14", "2026-10-04", 90),
            api(B, "2026-09-14", "2026-10-04", 91),
        ),
    )
    selected = ReportPeriod(
        KIND_RANGE, "2026-09-14..2026-10-04", date(2026, 9, 14), date(2026, 10, 4)
    )
    assert source.previous_for("rs", ("RS",), selected, TODAY) is None


def test_previous_actual_window_is_unknown_if_current_cadences_differ(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-08-31", "2026-09-13", 80),
            api(A, "2026-09-14", "2026-10-04", 90),
            api(B, "2026-09-14", "2026-09-27", 91),
        ),
    )
    selected = ReportPeriod(
        KIND_RANGE, "2026-09-14..2026-10-04", date(2026, 9, 14), date(2026, 10, 4)
    )
    assert source.previous_for("rs", ("RS",), selected, TODAY) is None


def test_missing_predecessor_and_non_source_range_do_not_fabricate_previous_dates(monkeypatch):
    stub(monkeypatch, rows=(api(A, "2026-09-14", "2026-10-04", 90),))
    selected = ReportPeriod(
        KIND_RANGE, "2026-09-14..2026-10-04", date(2026, 9, 14), date(2026, 10, 4)
    )
    assert source.previous_for("rs", ("RS",), selected, TODAY) is None
    invented = ReportPeriod(
        KIND_RANGE, "2026-09-15..2026-10-04", date(2026, 9, 15), date(2026, 10, 4)
    )
    assert source.previous_for("rs", ("RS",), invented, TODAY) is None


def test_legacy_only_fallback_units_make_source_previous_window_unknown(monkeypatch):
    stub(
        monkeypatch,
        rows=(
            api(A, "2026-08-31", "2026-09-13", 80),
            api(A, "2026-09-14", "2026-10-04", 90),
        ),
        old=(legacy(B, 75, begin=date(2026, 9, 16), end=date(2026, 9, 30)),),
    )
    selected = ReportPeriod(
        KIND_RANGE, "2026-09-14..2026-10-04", date(2026, 9, 14), date(2026, 10, 4)
    )
    assert source.previous_for("rs", ("RS",), selected, TODAY) is None


def test_previous_actual_window_reader_has_bounded_history_and_respects_country_scope(monkeypatch):
    calls = []

    def rows(**kw):
        calls.append(kw)
        return (
            api(A, "2026-08-31", "2026-09-13", 80),
            api(A, "2026-09-14", "2026-10-04", 90),
            api(B, "2026-08-24", "2026-09-13", 81, country="BG"),
            api(B, "2026-09-14", "2026-10-04", 91, country="BG"),
        )

    monkeypatch.setattr(read, "source_rating_periods", rows)
    monkeypatch.setattr(read, "score_facts", lambda **kw: ())
    selected = ReportPeriod(
        KIND_RANGE, "2026-09-14..2026-10-04", date(2026, 9, 14), date(2026, 10, 4)
    )
    previous = source.previous_for("rs", ("RS",), selected, TODAY)
    assert previous is not None and previous.begin == date(2026, 8, 31)
    assert len(calls) == 1
    assert calls[0]["countries"] == ("RS",)
    assert (selected.begin - calls[0]["begin"]).days == source.PREVIOUS_LOOKBACK_DAYS


def test_calendar_and_future_frames_are_left_to_parent_without_source_queries(monkeypatch):
    def forbidden(**kw):
        raise AssertionError("calendar and future frames do not need this source lookup")

    monkeypatch.setattr(read, "source_rating_periods", forbidden)
    assert source.previous_for("rs", ("RS",), month_period(2026, 9), TODAY) is None
    assert source.previous_for("rs", ("RS",), quarter_period(2026, 3), TODAY) is None
    future = ReportPeriod(
        KIND_RANGE, "2026-12-01..2026-12-14", date(2026, 12, 1), date(2026, 12, 14)
    )
    assert source.previous_for("rs", ("RS",), future, TODAY) is None
