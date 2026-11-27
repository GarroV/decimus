"""Деньги, общие расчёты и граница партнёра у новых читающих инструментов MCP."""

from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from src.db import dodois_metrics as dm
from src.db.errors import DbError
from src.db.reach import Reach
from src.mcp import business_read as tool
from src.mcp.catalogue import find
from src.mcp.errors import ToolError
from src.mcp.policy import permits_tool
from src.ratings import quality_data as quality

MONTH = date(2026, 10, 1)


@pytest.fixture
def data(monkeypatch):
    class Clock(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 27)

    monkeypatch.setattr(tool, "date", Clock)
    monkeypatch.setattr(
        tool,
        "reach_of",
        lambda t: Reach(t, None, None if t == "HQ" else ("RS",) if t == "PARTNER" else ()),
    )
    monkeypatch.setattr(
        tool.read, "countries", lambda: [SimpleNamespace(code=c, is_imf=True) for c in ("AM", "RS")]
    )
    names = {"u1": ("RS", "Demo-1"), "u2": ("RS", "Demo-2"), "a1": ("AM", "Armenia-1")}
    monkeypatch.setattr(
        tool.agg_store,
        "units",
        lambda codes: [
            SimpleNamespace(dodo_id=uid, name=name)
            for uid, (cc, name) in names.items()
            if cc in codes
        ],
    )
    rows = {
        ("RS", MONTH): [
            dm.UnitSales("u1", "MobileApp", "Delivery", 2, D(90), "RSD"),
            dm.UnitSales("u2", "Aggregator", "DineIn", 1, D(30), "RSD"),
        ],
        ("RS", date(2026, 9, 1)): [
            dm.UnitSales("u1", "MobileApp", "Delivery", 1, D(30), "RSD"),
            dm.UnitSales("u2", "Aggregator", "DineIn", 2, D(30), "RSD"),
        ],
        ("RS", date(2025, 10, 1)): [dm.UnitSales("u1", "MobileApp", "Delivery", 1, D(40), "RSD")],
        ("AM", MONTH): [dm.UnitSales("a1", "Website", "Delivery", 4, D(2000), "AMD")],
    }
    calls = []

    def sales(code, month):
        calls.append(code)
        return rows.get((code, month), [])

    monkeypatch.setattr(tool.dodois_metrics, "unit_sales", sales)
    monkeypatch.setattr(tool.dodois_metrics, "unit_aggregator_orders", lambda *a: [])
    monkeypatch.setattr(tool.dodois_metrics, "kind_loads", lambda: [])
    return rows, calls


def test_sales_weighted_average_comparisons_and_currencies(data):
    result = tool.sales_summary(tenant="HQ", month="2026-10")
    countries = {r["country"]: r for r in result["countries"]}
    rs = countries["RS"]
    assert (rs["currency"], rs["revenue"], rs["orders"], rs["average_check"]) == (
        "RSD",
        "120",
        3,
        "40.00",
    )
    assert countries["AM"]["currency"] == "AMD" and countries["AM"]["revenue"] == "2000"
    assert "revenue" not in result  # no mixed-currency network total
    assert rs["comparison"]["previous_month"]["change"]["revenue"]["percent"] == "100.00"
    assert rs["comparison"]["previous_year"]["change"]["revenue"]["percent"] == "200.00"
    assert rs["channels"]["delivery"]["orders"] == 2
    assert rs["source_groups"]["aggregators"]["orders"] == 1
    assert result["next_offset"] is None


def test_partner_scope_pagination_and_forbidden_country(data):
    _, calls = data
    page = tool.sales_summary(tenant="PARTNER", month="2026-10", limit=1)
    assert {c["country"] for c in page["countries"]} == {"RS"}
    assert page["total_units"] == 2 and page["next_offset"] == 1
    assert set(calls) == {"RS"}
    second = tool.sales_summary(tenant="PARTNER", month="2026-10", limit=1, offset=1)
    assert page["units"][0]["unit_id"] != second["units"][0]["unit_id"]
    with pytest.raises(ToolError, match="недоступна"):
        tool.sales_summary(tenant="PARTNER", month="2026-10", country="AM")


def test_missing_data_zero_denominator_and_current_month(data):
    rows, _ = data
    result = tool.sales_summary(tenant="HQ", country="RS", month="2026-08")
    assert result["status"] == "no_data" and result["countries"][0]["revenue"] is None
    assert tool._change(10, 0) == {"absolute": "10", "percent": None}
    rows["RS", date(2026, 11, 1)] = rows["RS", MONTH]
    current = tool.sales_summary(tenant="HQ", month="2026-11", country="RS")
    assert current["incomplete_month"]
    assert current["countries"][0]["comparison"]["previous_month"]["change"] is None


def test_country_aggregator_fallback_matches_sum_of_units(data, monkeypatch):
    monkeypatch.setattr(
        tool.dodois_metrics,
        "unit_aggregator_orders",
        lambda code, month: (
            [dm.UnitAggregatorOrders("u1", "Wolt", 4, None)]
            if code == "RS" and month == MONTH
            else []
        ),
    )
    result = tool.sales_summary(tenant="PARTNER", month="2026-10")
    country = result["countries"][0]
    assert country["orders"] == sum(u["orders"] for u in result["units"]) == 7
    assert country["source_groups"]["aggregators"]["orders"] == 5
    assert country["average_check"] == "40.00"


def test_mixed_currency_and_database_error_are_refusals(data, monkeypatch):
    rows, _ = data
    rows["RS", MONTH].append(dm.UnitSales("u1", "Website", "Delivery", 1, D(4), "EUR"))
    with pytest.raises(ToolError, match="валюты"):
        tool.sales_summary(tenant="HQ", month="2026-10", country="RS")

    def fail(*a):
        raise DbError("database offline")

    monkeypatch.setattr(tool.dodois_metrics, "unit_sales", fail)
    with pytest.raises(ToolError, match="не отсутствие"):
        tool.sales_summary(tenant="HQ", month="2026-10", country="RS")


@pytest.mark.parametrize("month", ["2026-13", "2099-01", "last month"])
def test_invalid_month_is_rejected(month):
    with pytest.raises(ToolError, match="month"):
        tool.sales_summary(tenant="HQ", month=month)


def test_quality_uses_same_calculation_customer_maps_and_native_scales(data, monkeypatch):
    rows, _ = data
    unit = quality._unit(
        "u1",
        "Demo-1",
        "RS",
        scores=[],
        audit=None,
        maps=(("Google", D("4.5"), 10), ("Yandex", D(4), 20)),
        sales=rows["RS", MONTH][:1],
        agg_orders=[dm.UnitAggregatorOrders("u1", "Wolt", 1, None)],
        kr=dm.UnitKr("u1", D(4), 2, D(5), 1),
        agg_scores={"wolt": (D(9), 10)},
        periods=[dm.UnitRatingPeriod("u1", "rko", MONTH, date(2026, 10, 7), D(90), "published", 5)],
    )
    country = quality._country("RS", [unit], "RSD", quality.DODOIS_OK)

    def load(reach, codes, month, *, with_audit):
        assert codes == ("RS",) and with_audit is False
        return {"RS": country}

    monkeypatch.setattr(quality, "load_month", load)
    result = tool.quality_summary(tenant="PARTNER", month="2026-10")
    row = result["units"][0]
    assert row["values"]["kr"] == str(unit.values["kr"])
    assert row["values"]["rko"] == "90" and "audit" not in row["values"]
    assert {m["provider"] for m in row["maps"]} == {"Google", "Yandex"}
    assert row["customer_ratings"]["dine_in_count"] == 2
    assert row["aggregators"][0]["scale"] == 10
    assert row["aggregators"][0]["score5"] == "4.5"
    assert result["countries"][0]["values"]["total"] == str(country.values["total"])
    assert row["currency"] == "RSD"


def test_new_tools_read_only_for_both_admin_types():
    for name in ("sales_summary", "quality_summary"):
        spec = find(name)
        assert spec is not None and not spec.writes
        assert permits_tool("admin", "HQ", spec)
        assert permits_tool("admin", "PARTNER", spec)
        assert not permits_tool("unknown", "HQ", spec)
        assert "tenant" not in spec.input_schema["properties"]
