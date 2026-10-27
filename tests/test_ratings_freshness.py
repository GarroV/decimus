"""Цвет свежести источников рейтингов (D659): границы дней у каждого вида."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from src.ratings import freshness as f

TODAY = date(2026, 10, 27)


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


def test_worst_takes_the_reddest() -> None:
    assert f.worst([f.Status.FRESH, f.Status.STALE, f.Status.LAG]) is f.Status.STALE
    assert f.worst([f.Status.FRESH, f.Status.LAG]) is f.Status.LAG
    assert f.worst([]) is None


def test_build_has_fixed_order_and_missing_data_is_red() -> None:
    rows = f.build(
        today=TODAY,
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
        *("fresh", "stale", "fresh", "lag", "lag", "fresh", "stale", "fresh"),
    ]


def test_unconnected_control_sheet_has_no_row() -> None:
    rows = f.build(
        today=TODAY, rs=None, rko=None, sheet_checked=None, maps_loaded=_at(0), aggregators={}
    )
    assert [r.kind for r in rows] == ["rs", "rko", "maps"]
