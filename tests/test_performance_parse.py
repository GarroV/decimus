"""Контракт операционных ответов: веса, границы и отсутствие выдуманных нулей."""

from datetime import date
from decimal import Decimal

import pytest

from src.dodois import performance_parse as parse
from src.domain.performance import Window, aggregate

A, B, FOREIGN = "a" * 32, "b" * 32, "c" * 32
PERIOD = Window(date(2026, 11, 1), date(2026, 11, 2))
ZONE = "Europe/Belgrade"


def run(parser, body, *, country="RS", period=PERIOD, expected=None):
    return parser(body, country, period, ZONE, expected if expected is not None else [A, B])


def test_sales_totals_missing_unit_and_currency_history():
    body = {"result": [{"unitId": A, "sales": 12.75, "ordersCount": 3}]}
    revenue, orders, absent_revenue, absent_orders = run(parse.sales, body)
    assert revenue.amount == Decimal("12.75") and revenue.currency == "RSD"
    assert orders.amount == 3 and orders.currency is None
    assert absent_revenue.amount is absent_orders.amount is None
    assert absent_orders.reason == "missing_unit"
    old = Window(date(2025, 11, 1), date(2025, 11, 2))
    assert run(parse.sales, body, country="BG", period=old)[0].currency == "BGN"
    assert run(parse.sales, body, country="BG")[0].currency == "EUR"
    crossing = Window(date(2025, 12, 31), date(2026, 1, 1))
    changed = run(parse.sales, body, country="BG", period=crossing)
    assert changed[0].amount is None and changed[0].reason == "currency_change_within_window"
    assert changed[1].amount == 3
    unknown = run(parse.sales, body, country="ZZ")[0]
    assert unknown.amount is None and unknown.reason == "unknown_currency"


@pytest.mark.parametrize(
    "parser,key,field,count,metric",
    [
        (
            parse.delivery,
            "unitsStatistics",
            "avgDeliveryOrderFulfillmentTime",
            "deliveryOrdersCount",
            "delivery_seconds",
        ),
        (
            parse.cooking,
            "ordersHandoverStatistics",
            "avgCookingTime",
            "ordersCount",
            "restaurant_cooking_seconds",
        ),
    ],
)
def test_means_use_source_counts_and_zero_is_unavailable(parser, key, field, count, metric):
    body = {
        key: [
            {"unitId": A, field: 100, count: 1, "ordersCountOverall": 5000},
            {"unitId": B, field: 200, count: 3, "ordersCountOverall": 1},
        ]
    }
    rows = run(parser, body)
    assert rows[0].metric == metric
    assert rows[1].numerator == 600 and rows[1].denominator == 3
    assert rows[1].reason == "source_rounded_average"
    total = aggregate(rows, expected_units=2)
    assert total.amount == 175
    zero = run(parser, {key: [{"unitId": A, field: 0, count: 0}]})
    assert zero[0].amount is None and zero[0].reason == "no_orders"
    assert zero[1].amount is None and zero[1].reason == "missing_unit"
    assert run(parser, {key: []})[0].amount is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"result": None},
        {"result": {}},
        {"result": [None]},
        {"result": [{"unitId": FOREIGN, "sales": 1, "ordersCount": 1}]},
        {"result": [{"unitId": A, "sales": 1, "ordersCount": 1}] * 2},
        {"result": [{"unitId": A, "sales": float("nan"), "ordersCount": 1}]},
        {"result": [{"unitId": A, "sales": float("inf"), "ordersCount": 1}]},
        {"result": [{"unitId": A, "sales": True, "ordersCount": 1}]},
        {"result": [{"unitId": A, "sales": "12.00", "ordersCount": 1}]},
        {"result": [{"unitId": A, "sales": 1, "ordersCount": -1}]},
        {"result": [{"unitId": A, "sales": 1, "ordersCount": 0.5}]},
    ],
)
def test_sales_rejects_wrong_shape_foreign_duplicate_and_nonfinite(body):
    with pytest.raises(ValueError):
        run(parse.sales, body)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True])
def test_delivery_rejects_invalid_mean(value):
    with pytest.raises(ValueError):
        run(
            parse.delivery,
            {
                "unitsStatistics": [
                    {
                        "unitId": A,
                        "avgDeliveryOrderFulfillmentTime": value,
                        "deliveryOrdersCount": 1,
                    }
                ]
            },
        )


def event(identity, start, end, *, unit=A, kind="Complete", channel="Delivery"):
    return {
        "id": identity,
        "unitId": unit,
        "startedAtLocal": start,
        "endedAtLocal": end,
        "salesChannelName": channel,
        "channelStopType": kind,
    }


def test_stops_clip_union_open_end_and_redirection():
    body = {
        "stopSalesBySalesChannels": [
            event("1", "2026-10-31T23:00:00", "2026-11-01T01:00:00"),
            event("2", "2026-11-01T00:30:00", "2026-11-01T02:00:00", channel="Dine-in"),
            event("3", "2026-11-02T23:00:00", None),
            event("4", "2026-11-01T10:00:00", "2026-11-01T11:00:00", kind="Redirection"),
            event("5", "2026-11-03T00:00:00", "2026-11-03T01:00:00"),
        ]
    }
    seconds, count, empty_seconds, empty_count = run(parse.stops, body)
    assert seconds.amount == 10800 and count.amount == 3
    assert empty_seconds.amount == empty_count.amount == 0
    assert all(
        row.status == "partial" and row.reason == "boundary_semantics_unverified"
        for row in (seconds, count, empty_seconds, empty_count)
    )


def test_stops_elapsed_time_uses_local_timezone_across_dst():
    day = Window(date(2026, 10, 25), date(2026, 10, 25))
    body = {"stopSalesBySalesChannels": [event("1", "2026-10-25T00:00:00", "2026-10-26T00:00:00")]}
    assert run(parse.stops, body, period=day)[0].amount == 25 * 3600


@pytest.mark.parametrize(
    "events",
    [
        [event("1", "2026-11-01T01:00:00", None, unit=FOREIGN)],
        [event("1", "2026-11-01T01:00:00", None)] * 2,
        [event("1", "2026-11-01T01:00:00Z", None)],
        [event("1", "2026-11-01T02:00:00", "2026-11-01T01:00:00")],
        [
            {
                "id": "1",
                "unitId": A,
                "startedAt": "2026-11-01T01:00:00",
                "endedAt": None,
                "salesChannelName": "Delivery",
                "channelStopType": "Complete",
            }
        ],
    ],
)
def test_stops_reject_invalid_or_implicit_local_windows(events):
    with pytest.raises(ValueError):
        run(parse.stops, {"stopSalesBySalesChannels": events})


def test_vouchers_complete_pages_dedup_and_only_batch_zeroes():
    record = {
        "unitId": A,
        "orderId": "order-1",
        "courierStaffId": "private",
        "issuerName": "private",
        "orderNumber": "private",
    }
    result = run(parse.vouchers, {"vouchers": [record, record], "isEndOfListReached": True})
    assert [row.amount for row in result] == [1, 0]
    assert "private" not in repr(result)
    empty = run(parse.vouchers, {"vouchers": [], "isEndOfListReached": True}, expected=[A])
    assert len(empty) == 1 and empty[0].amount == 0 and empty[0].status == "complete"


@pytest.mark.parametrize(
    "body",
    [
        {"vouchers": []},
        {"vouchers": [], "isEndOfListReached": False},
        {"vouchers": [], "isEndOfListReached": 1},
        {"vouchers": [{"unitId": FOREIGN, "orderId": "o"}], "isEndOfListReached": True},
        {
            "vouchers": [{"unitId": A, "orderId": "o"}, {"unitId": B, "orderId": "o"}],
            "isEndOfListReached": True,
        },
    ],
)
def test_vouchers_rejects_unfinished_pages_or_foreign_data(body):
    with pytest.raises(ValueError):
        run(parse.vouchers, body)


def lfl_row(**changes):
    return {
        "unitId": A,
        "countryId": "rs",
        "date": "2026-11-01",
        "lflRevenue": 0.05,
        "lflOrder": -0.02,
        **changes,
    }


def test_native_lfl_preserves_raw_query_and_bucket_without_averaging():
    rows = parse.native_lfl(
        {"lfl": [lfl_row(), lfl_row(date="2026-11-02")]}, "RS", PERIOD, "Day", [A]
    )
    assert len(rows) == 2
    assert rows[0].revenue_raw == Decimal("0.05")
    assert rows[0].orders_raw == Decimal("-0.02")
    assert rows[0].query == PERIOD and rows[0].date == date(2026, 11, 1)
    assert rows[0].json()["unit"] == "source_value"
    country = lfl_row()
    del country["unitId"]
    assert (
        parse.native_lfl({"lfl": [country]}, "RS", PERIOD, "Month", ["RS"], by_country=True)[
            0
        ].subject_id
        == "RS"
    )
    assert parse.native_lfl({"lfl": []}, "RS", PERIOD, "Day", [A]) == []


@pytest.mark.parametrize(
    "rows",
    [
        [lfl_row(unitId=FOREIGN)],
        [lfl_row(countryId="by")],
        [lfl_row(), lfl_row()],
        [lfl_row(lflRevenue=float("nan"))],
        [lfl_row(date="2026-02-30")],
    ],
)
def test_native_lfl_rejects_foreign_duplicate_and_invalid_values(rows):
    with pytest.raises(ValueError):
        parse.native_lfl({"lfl": rows}, "RS", PERIOD, "Day", [A])
