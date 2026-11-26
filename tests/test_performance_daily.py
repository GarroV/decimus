from datetime import date
from decimal import Decimal

import pytest

from src.dodois import performance_daily as daily
from src.dodois.client import Response
from src.domain.performance import Window
from src.domain.performance_series import daily_json


def test_native_days_are_sorted_not_distributed_and_singleton_request_overlaps(monkeypatch):
    saved, queries = [], []
    monkeypatch.setattr(
        daily.store, "upsert_observations", lambda rows: saved.extend(rows) or len(rows)
    )

    def get(_path, query):
        queries.append(query)
        start, end = date.fromisoformat(query["fromDate"]), date.fromisoformat(query["toDate"])
        assert start < end and (end - start).days < 10
        days = [end, start]
        return Response(
            200,
            {},
            {
                "result": [
                    {"date": day.isoformat(), "sales": day.day * 10, "ordersCount": day.day}
                    for day in days
                ]
            },
        )

    window = Window(date(2026, 11, 1), date(2026, 11, 11))
    assert daily.collect_finance("BG", window, "Europe/Sofia", get) == 6
    assert [(r.period.start.day, r.value) for r in saved if r.metric == "revenue"] == [
        (1, Decimal(10)),
        (10, Decimal(100)),
        (11, Decimal(110)),
    ]
    points = daily_json("BG", {"current": window}, saved)["current"]
    assert len(points) == 11
    assert points[1]["metrics"]["revenue"]["value"] is None
    assert points[9]["metrics"]["revenue"]["value"] == "100"
    assert points[0]["metrics"]["revenue"]["coverage"]["scope"] == "source_country"


def test_refused_later_chunk_does_not_replace_prior_success(monkeypatch):
    writes = []
    monkeypatch.setattr(daily.store, "upsert_observations", lambda rows: writes.append(rows))
    calls = 0

    def get(_path, _query):
        nonlocal calls
        calls += 1
        return (
            Response(200, {}, {"result": [{"date": "2026-11-01", "sales": 12, "ordersCount": 2}]})
            if calls == 1
            else Response(503, {}, {})
        )

    with pytest.raises(ValueError):
        daily.collect_finance(
            "BG", Window(date(2026, 11, 1), date(2026, 11, 11)), "Europe/Sofia", get
        )
    assert writes == []


def test_daily_zero_is_a_real_point_and_previous_currency_is_retained(monkeypatch):
    saved = []
    monkeypatch.setattr(
        daily.store, "upsert_observations", lambda rows: saved.extend(rows) or len(rows)
    )
    daily.collect_finance(
        "BG",
        Window(date(2025, 11, 1), date(2025, 11, 1)),
        "Europe/Sofia",
        lambda _path, _query: Response(
            200, {}, {"result": [{"date": "2025-11-01", "sales": 0, "ordersCount": 0}]}
        ),
    )
    point = daily_json("BG", {"yoy": Window(date(2025, 11, 1), date(2025, 11, 1))}, saved)["yoy"][0]
    assert point["metrics"]["revenue"]["value"] == "0"
    assert point["metrics"]["revenue"]["currency"] == "BGN"
    assert point["metrics"]["delivery_seconds"]["value"] is None
