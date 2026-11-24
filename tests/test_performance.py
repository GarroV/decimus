"""Риски сравнений: равное отсечение, веса, отсутствие, нулевая база и валюта."""

from datetime import UTC, date, datetime
from decimal import Decimal as D

import pytest

from src.domain.performance import (
    NativeLfl,
    Observation,
    Window,
    aggregate,
    comparison_json,
    comparison_windows,
    last_complete_day,
    observation_json,
)
from src.domain.performance_feed import country_json

UNIT = "aa" * 16
OTHER = "bb" * 16
PERIOD = Window(date(2026, 11, 1), date(2026, 11, 15))


def obs(value="10", **kwargs):
    return Observation(
        "RS",
        UNIT,
        "orders",
        PERIOD,
        D(value) if value is not None else None,
        loaded_at=datetime(2026, 11, 16, tzinfo=UTC),
        covered_units=1,
        expected_units=1,
        **kwargs,
    )


def test_same_cutoff_and_leap_month():
    periods = comparison_windows(date(2026, 11, 15))
    assert periods["mom"] == Window(date(2026, 10, 1), date(2026, 10, 15))
    assert periods["yoy"] == Window(date(2025, 11, 1), date(2025, 11, 15))
    assert comparison_windows(date(2024, 3, 31))["mom"].end == date(2024, 2, 29)
    assert comparison_windows(date(2024, 2, 29))["yoy"].end == date(2023, 2, 28)
    assert comparison_windows(date(2026, 1, 1))["mom"].end == date(2025, 12, 1)


def test_last_complete_day_uses_country_timezone():
    now = datetime(2026, 11, 15, 23, 30, tzinfo=UTC)
    assert last_complete_day(["Europe/Belgrade"], now=now) == date(2026, 11, 15)
    assert last_complete_day(["America/Mexico_City"], now=now) == date(2026, 11, 14)
    with pytest.raises(ValueError):
        last_complete_day([], now=now)


def test_weighted_mean_and_no_mean_of_means():
    a = Observation("RS", UNIT, "delivery_seconds", PERIOD, numerator=D(900), denominator=D(3))
    b = Observation("RS", OTHER, "delivery_seconds", PERIOD, numerator=D(900), denominator=D(1))
    total = aggregate([a, b], expected_units=2)
    assert total.amount == D(450)
    assert total.status == "complete"
    without_weights = Observation("RS", OTHER, "delivery_seconds", PERIOD, value=D(900))
    partial = aggregate([a, without_weights], expected_units=2)
    assert partial.amount == D(300) and partial.status == "partial"
    assert partial.covered_units == 1
    assert observation_json(without_weights)["aggregation"] == "source_average"


def test_missing_zero_and_partial_are_distinct():
    assert observation_json(None)["value"] is None
    assert observation_json(obs("0"))["value"] == "0"
    assert comparison_json(obs("10"), obs("0"))["delta_pct"] is None
    assert comparison_json(obs("10"), obs("0"))["comparison_status"] == "zero_baseline"
    assert comparison_json(obs("10"), obs("5"))["delta_pct"] == "100"
    assert comparison_json(obs("10", status="partial"), obs("5"))["delta_pct"] is None
    total = aggregate([obs()], expected_units=2)
    assert total.status == "partial" and total.covered_units == 1
    assert aggregate([obs()], expected_units=None).status == "partial"


def test_currency_mismatch_and_unknown_currency():
    eur = Observation("BG", "BG", "revenue", PERIOD, value=D(100), currency="EUR")
    bgn = Observation("BG", "BG", "revenue", PERIOD, value=D(100), currency="BGN")
    assert comparison_json(eur, bgn)["comparison_status"] == "currency_mismatch"
    assert comparison_json(eur, bgn)["delta_pct"] is None
    unknown = Observation("BG", "BG", "revenue", PERIOD, value=D(100))
    assert observation_json(unknown)["value"] is None
    with pytest.raises(ValueError):
        aggregate([eur, bgn], expected_units=2)


def test_stale_and_invalid_values():
    assert observation_json(obs(), now=datetime(2026, 11, 18, tzinfo=UTC))["stale"] is True
    for value in (D("NaN"), D("Infinity"), 1.5):
        with pytest.raises(ValueError):
            Observation("RS", UNIT, "orders", PERIOD, value=value)
    with pytest.raises(ValueError):
        Observation("RS", UNIT, "delivery_seconds", PERIOD, numerator=D(1))


def test_native_lfl_preserves_raw_buckets_not_mtd_percentage():
    lfl = NativeLfl("RS", UNIT, PERIOD, "Day", date(2026, 11, 1), D("0.05"), D("0.02"))
    result = lfl.json()
    assert result["revenue_raw"] == "0.05"
    assert result["query"] == PERIOD.json()
    assert result["date"] == "2026-11-01"
    assert result["unit"] == "source_value"
    assert result["status"] == "source_period_unverified"


def test_country_scope_does_not_guess_active_units_or_average_weights():
    row = Observation("RS", UNIT, "delivery_seconds", PERIOD, value=D(300))
    payload = country_json(
        "RS",
        name="Serbia",
        as_of=PERIOD.end,
        timezone="Europe/Belgrade",
        timezone_fallback=False,
        rows=[row],
        lfl=[],
        names={UNIT: ("RS", "Testville-1")},
        loads=[],
    )
    assert payload["metrics"]["delivery_seconds"]["current"]["value"] is None
    assert payload["units"][0]["metrics"]["delivery_seconds"]["current"]["value"] == "300"
    assert payload["metrics"]["orders"]["current"]["status"] == "unavailable"


def test_feed_does_not_publish_native_bucket_as_mtd_growth():
    bucket = NativeLfl("RS", "RS", PERIOD, "Month", PERIOD.start, D("0.05"), D("0.02"))
    payload = country_json(
        "RS",
        name="Serbia",
        as_of=PERIOD.end,
        timezone="Europe/Belgrade",
        timezone_fallback=False,
        rows=[],
        lfl=[bucket],
        names={},
        loads=[],
    )
    native = payload["lfl"][0]
    assert native["status"] == "source_period_unverified"
    assert native["reason"] == "native_bucket_not_request_slice"
    assert "delta_pct" not in native
    assert "native_lfl_revenue_pct" not in payload["metrics"]


@pytest.mark.parametrize("metric", ["delivery_seconds", "restaurant_cooking_seconds"])
def test_zero_order_units_count_as_covered_without_changing_weighted_mean(metric):
    positive = Observation(
        "RS",
        UNIT,
        metric,
        PERIOD,
        numerator=D(300),
        denominator=D(3),
        covered_units=1,
        expected_units=1,
        reason="source_rounded_average",
        loaded_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    zero = Observation(
        "RS",
        OTHER,
        metric,
        PERIOD,
        status="unavailable",
        reason="no_orders",
        covered_units=0,
        expected_units=1,
        loaded_at=datetime(2026, 11, 15, tzinfo=UTC),
    )
    total = aggregate([positive, zero], expected_units=2)
    assert total.status == "complete" and total.amount == D(100)
    assert total.numerator == D(300) and total.denominator == D(3)
    assert total.covered_units == total.expected_units == 2
    assert total.reason == "source_rounded_average"
    assert total.loaded_at == zero.loaded_at
    missing = Observation("RS", OTHER, metric, PERIOD, status="unavailable", reason="missing_unit")
    incomplete = aggregate([positive, missing], expected_units=2)
    assert incomplete.status == "partial" and incomplete.covered_units == 1
    assert incomplete.reason == "source_rounded_average"


def test_all_zero_order_mean_is_unavailable_with_full_coverage_and_no_orders_reason():
    rows = [
        Observation(
            "RS",
            unit,
            "delivery_seconds",
            PERIOD,
            status="unavailable",
            reason="no_orders",
            covered_units=0,
            expected_units=1,
        )
        for unit in (UNIT, OTHER)
    ]
    total = aggregate(rows, expected_units=2)
    assert total.status == "unavailable" and total.amount is None
    assert total.covered_units == total.expected_units == 2
    assert total.numerator == total.denominator == D(0)
    assert total.reason == "no_orders"
    payload = country_json(
        "RS",
        name="Serbia",
        as_of=PERIOD.end,
        timezone="Europe/Belgrade",
        timezone_fallback=False,
        rows=[total],
        lfl=[],
        names={},
        loads=[],
    )
    current = payload["metrics"]["delivery_seconds"]["current"]
    assert current["value"] is None and current["status"] == "unavailable"
    assert current["coverage"] == {"covered_units": 2, "expected_units": 2}
    assert current["reason"] == "no_orders"


@pytest.mark.parametrize("metric,currency", [("revenue", "RSD"), ("orders", None)])
def test_native_country_finance_scope_allows_percentage_without_unit_counts(metric, currency):
    current = Observation(
        "RS",
        "RS",
        metric,
        PERIOD,
        value=D(120),
        currency=currency,
        source="dodois/finances/sales/country",
    )
    previous = Observation(
        "RS",
        "RS",
        metric,
        comparison_windows(PERIOD.end)["mom"],
        value=D(100),
        currency=currency,
        source="dodois/finances/sales/country",
    )
    result = observation_json(current)
    assert result["status"] == "complete" and result["reason"] is None
    assert result["coverage"] == {
        "scope": "source_country",
        "covered_units": None,
        "expected_units": None,
    }
    assert comparison_json(current, previous)["delta_pct"] == "20.0"


def test_unknown_unit_and_other_country_sources_remain_partial():
    for subject, source in (
        (UNIT, "dodois/finances/sales/country"),
        ("RS", "dodois/finances/sales/units"),
        ("RS", "dodois/finances/sales/country:other"),
    ):
        row = Observation("RS", subject, "orders", PERIOD, value=D(100), source=source)
        result = observation_json(row)
        assert result["status"] == "partial"
        assert result["reason"] == "unknown_coverage"
        assert "scope" not in result["coverage"]
