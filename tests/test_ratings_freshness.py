"""Цвет свежести источников рейтингов (D659): границы дней у каждого вида."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from src.ratings import freshness as f

TODAY = date(2026, 10, 27)


NOW = datetime.combine(TODAY, time(1, 30), UTC)


def _at(days_ago: int, hour: int = 8) -> datetime:
    return datetime.combine(TODAY - timedelta(days=days_ago), time(hour), UTC)


@pytest.mark.parametrize(
    ("kind", "age", "want"),
    [
        ("rs", 0, f.Status.FRESH),
        ("rs", 22, f.Status.FRESH),
        ("rs", 23, f.Status.LAG),
        ("rs", 25, f.Status.LAG),
        ("rs", 26, f.Status.STALE),
        ("rko", 11, f.Status.FRESH),
        ("rko", 12, f.Status.LAG),
        ("rko", 14, f.Status.LAG),
        ("rko", 15, f.Status.STALE),
    ],
)
def test_period_boundaries(kind: str, age: int, want: f.Status) -> None:
    assert f.classify_period(kind, TODAY - timedelta(days=age), TODAY) is want


@pytest.mark.parametrize(
    ("days_ago", "want"),
    [(0, f.Status.FRESH), (1, f.Status.LAG), (3, f.Status.LAG), (4, f.Status.STALE)],
)
def test_routine_boundaries(days_ago: int, want: f.Status) -> None:
    assert f.classify_age(_at(days_ago), TODAY) is want


def test_routine_counts_calendar_days_not_hours() -> None:
    assert f.classify_age(_at(1, hour=23), TODAY) is f.Status.LAG


@pytest.mark.parametrize(
    ("hours", "want"),
    [
        (8, f.Status.FRESH),
        (36, f.Status.FRESH),
        (37, f.Status.LAG),
        (96, f.Status.LAG),
        (97, f.Status.STALE),
    ],
)
def test_daily_source_is_judged_by_age_in_hours_not_by_date(hours: int, want: f.Status) -> None:
    # Сбор пришёл вчера в 17:25, на экране 01:30 — календарно «вчера», но возраст 8 часов.
    assert f.classify_daily(NOW - timedelta(hours=hours), NOW) is want


def test_collapse_aggregators_keeps_worst_color_and_oldest_arrival() -> None:
    rows = f.build(
        today=TODAY,
        now=NOW,
        rs=None,
        rko=None,
        sheet_checked=None,
        maps_loaded=_at(0),
        aggregators={"wolt": NOW - timedelta(hours=8), "glovo": NOW - timedelta(hours=50)},
    )
    one = [r for r in f.collapse_aggregators(rows) if r.kind == "agg"]
    assert len(one) == 1
    assert (one[0].count, one[0].status) == (2, f.Status.LAG)
    assert one[0].arrived == NOW - timedelta(hours=50)


def test_worst_takes_the_reddest() -> None:
    assert f.worst([f.Status.FRESH, f.Status.STALE, f.Status.LAG]) is f.Status.STALE
    assert f.worst([f.Status.FRESH, f.Status.LAG]) is f.Status.LAG
    assert f.worst([]) is None


def test_build_has_fixed_order_and_missing_data_is_red() -> None:
    rows = f.build(
        today=TODAY,
        now=NOW,
        rs=f.PeriodFact(date(2026, 10, 1), date(2026, 10, 15), _at(5)),
        rko=None,
        sheet_checked=_at(0),
        maps_loaded=_at(2),
        aggregators={"yandex_eda": _at(16), "zzz": _at(0), "glovo": _at(0), "wolt": _at(1)},
    )
    assert [(r.kind, r.code) for r in rows] == [
        ("rs", ""),
        ("rko", ""),
        ("sheet", ""),
        ("maps", ""),
        ("agg", "wolt"),
        ("agg", "glovo"),
        ("agg", "yandex_eda"),
        ("agg", "zzz"),
    ]
    assert [r.status.value for r in rows] == [
        *("fresh", "stale", "fresh", "lag", "fresh", "fresh", "stale", "fresh"),
    ]


def test_unconnected_control_sheet_has_no_row() -> None:
    rows = f.build(
        today=TODAY,
        now=NOW,
        rs=None,
        rko=None,
        sheet_checked=None,
        maps_loaded=_at(0),
        aggregators={},
    )
    assert [r.kind for r in rows] == ["rs", "rko", "maps"]
