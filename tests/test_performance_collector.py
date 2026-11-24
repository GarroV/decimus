"""Регрессии сбора: ограниченный бюджет, ротация и сохранность успешных окон."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest

from src.dodois import performance as collector
from src.domain.dodois import Login
from src.domain.performance import Observation, Window, observation_json

A, B = "a" * 32, "b" * 32
NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
CUTOFF = date(2026, 11, 23)
PERIOD = Window(date(2026, 11, 1), CUTOFF)


def login(country="RS"):
    return Login(
        country=country, contour="intl", source="test", issued_by="test",
        account_name=None, account_email=None, linked_at=NOW, scope="shared",
        units_total=1, units_open=1, refreshed_at=NOW, access_expires_at=None,
        checked_at=NOW, state="ok", reason=None,
    )


def response(status, body, headers=None):
    return collector.client.Response(status, headers or {}, body)


@pytest.mark.parametrize("failure", ["no_tokens", "network"])
def test_early_failures_persist_attempt_and_rotate_past_first_three(monkeypatch, failure):
    countries = ["AM", "AZ", "BG", "BY", "CY", "EE"]
    clock = [NOW]
    markers, recorded = {}, []

    def record(country, kind, period, *, error_code=None):
        recorded.append((country, kind, error_code))
        markers[country, kind, period] = {
            "kind": kind, "attempted_at": clock[0].isoformat(), "last_ok_at": None,
        }

    def states(countries, period):
        return [value for (country, _, window), value in markers.items()
                if country in countries and window == period]

    def discovery(_country):
        raise collector.client.DodoisError("network")

    monkeypatch.setattr(collector.logins, "list_logins", lambda: [login(cc) for cc in countries])
    monkeypatch.setattr(
        collector.logins, "read_tokens",
        lambda _: None if failure == "no_tokens" else collector.logins.Tokens("test", "test"),
    )
    monkeypatch.setattr(collector.client, "working_pizzerias", discovery)
    monkeypatch.setattr(collector.store, "record_load", record)
    monkeypatch.setattr(collector.store, "load_states", states)

    first = collector.run_pass(now=clock[0], sleep=lambda _: None)
    clock[0] += timedelta(hours=2)
    second = collector.run_pass(now=clock[0], sleep=lambda _: None)

    assert [out.country for out in first] == countries[:3]
    assert [out.country for out in second] == countries[3:]
    assert all(out.error == failure and out.kind == "country_attempt" for out in first + second)
    for country in countries:
        assert (country, "country_attempt", "in_progress") in recorded
        assert (country, "country_attempt", failure) in recorded


def test_one_budget_bounds_access_split_pagination_and_actual_429_retry(monkeypatch):
    calls, pauses = [], []

    def http_get(url, _access):
        query = parse_qs(urlsplit(url).query)
        calls.append(query)
        if len(calls) == 1:
            return response(403, {"code": "NoAccessToUnit"})
        if len(calls) == 3:
            return response(429, {}, {"retry-after": "2"})
        return response(200, {"vouchers": [], "isEndOfListReached": False})

    monkeypatch.setattr(collector.client, "_get", http_get)
    budget = collector.Budget(4)
    throttle = collector.Throttle(pauses.append, budget)
    with pytest.raises(collector.BudgetExhausted):
        collector._batch_rows("vouchers", login(), "test", [A, B], PERIOD,
                              "Europe/Belgrade", throttle)

    assert len(calls) == 4 and budget.remaining == 0
    assert calls[0]["units"] == [f"{A},{B}"]
    assert calls[1]["units"] == [A]
    assert calls[2]["skip"] == calls[3]["skip"] == ["100"]
    assert 2 in pauses


def test_empty_sales_keeps_old_unit_and_records_safe_incomplete_response(monkeypatch):
    previous = Observation(
        "RS", A, "revenue", PERIOD, value=Decimal("567.89"), currency="RSD",
        timezone="Europe/Belgrade", covered_units=1, expected_units=1,
        loaded_at=NOW - timedelta(days=2),
    )
    saved = {(A, "revenue"): previous}
    recorded = []

    def upsert(rows):
        saved.update(((row.subject_id, row.metric), row) for row in rows)
        return len(rows)

    def api(_contour, path, _query, _access, **_kwargs):
        if path.endswith("/sales/units"):
            return response(200, {"result": []})
        assert path.endswith("/sales/country")
        return response(200, {"result": {"sales": 1000, "ordersCount": 30}})

    states = [
        {"kind": kind, "attempted_at": NOW.isoformat(), "last_ok_at": NOW.isoformat()}
        for kind in ["delivery", "cooking", "stops", "vouchers", "lfl_day", "lfl_month"]
    ]
    monkeypatch.setattr(collector.logins, "read_tokens",
                        lambda _: collector.logins.Tokens("test", "test"))
    monkeypatch.setattr(collector.client, "working_pizzerias", lambda _: [A])
    monkeypatch.setattr(collector.metrics_store, "country_units", lambda _: [A])
    monkeypatch.setattr(collector.client, "api_get", api)
    monkeypatch.setattr(collector, "planned_windows", lambda _: [PERIOD])
    monkeypatch.setattr(collector.store, "load_states", lambda *_: states)
    monkeypatch.setattr(collector.store, "read_observations", lambda *_: list(saved.values()))
    monkeypatch.setattr(collector.store, "upsert_observations", upsert)
    monkeypatch.setattr(
        collector.store, "record_load",
        lambda country, kind, period, **kwargs: recorded.append((kind, kwargs.get("error_code"))),
    )

    outcomes = collector.collect_country(login(), now=NOW, as_of=CUTOFF, sleep=lambda _: None)

    assert saved[A, "revenue"] is previous
    assert saved[A, "revenue"].loaded_at == NOW - timedelta(days=2)
    assert [(out.kind, out.error) for out in outcomes] == [("sales", "incomplete_response")]
    assert ("sales", "incomplete_response") in recorded
    assert all(error in {None, "in_progress", "incomplete_response"} for _, error in recorded)


def test_native_country_totals_override_partial_historical_unit_cohort(monkeypatch):
    period = Window(date(2025, 11, 1), date(2025, 11, 23))
    saved = {}

    def api(_contour, path, query, _access, **_kwargs):
        assert query["from"] == "2025-11-01T00:00:00"
        assert query["to"] == "2025-11-24T00:00:00"
        if path.endswith("/sales/units"):
            return response(200, {"result": [
                {"unitId": A, "sales": 100, "ordersCount": 3},
                {"unitId": B, "sales": 40, "ordersCount": 2},
            ]})
        assert path.endswith("/sales/country") and "units" not in query
        return response(200, {"result": {"sales": 1500.75, "ordersCount": 400}})

    def upsert(rows):
        saved.update(((row.subject_id, row.metric), row) for row in rows)
        return len(rows)

    monkeypatch.setattr(collector.client, "api_get", api)
    monkeypatch.setattr(collector.store, "read_observations", lambda *_: [])
    monkeypatch.setattr(collector.store, "upsert_observations", upsert)

    collector._save_kind("sales", login(), "test", [A, B], {A}, period,
                         "Europe/Belgrade", collector.Throttle(lambda _: None, collector.Budget()),
                         current=False)

    country_revenue = saved["RS", "revenue"]
    assert country_revenue.amount == Decimal("1500.75")
    assert saved["RS", "orders"].amount == 400
    assert saved[A, "revenue"].amount == 100 and saved[B, "revenue"].amount == 40
    for metric in ("revenue", "orders"):
        result = observation_json(saved["RS", metric], now=NOW)
        assert result["status"] == "complete"
        assert result["coverage"] == {
            "covered_units": None, "expected_units": None, "scope": "source_country",
        }
        assert result["reason"] is None


def test_planned_windows_prioritize_comparisons_and_keep_twelve_full_months_unique():
    windows = collector.planned_windows(date(2026, 2, 28))
    assert windows[:3] == [
        Window(date(2026, 2, 1), date(2026, 2, 28)),
        Window(date(2026, 1, 1), date(2026, 1, 28)),
        Window(date(2025, 2, 1), date(2025, 2, 28)),
    ]
    full_months = {
        Window(date(2025, month, 1), date(2025, month, days))
        for month, days in [(2, 28), (3, 31), (4, 30), (5, 31), (6, 30),
                            (7, 31), (8, 31), (9, 30), (10, 31), (11, 30), (12, 31)]
    } | {Window(date(2026, 1, 1), date(2026, 1, 31))}
    assert full_months.issubset(windows)
    assert len(windows) == len(set(windows)) == 14


def test_closed_history_due_after_thirty_days_respects_retry_backoff():
    def state(ok_age, attempt_age):
        return [{"kind": "sales", "last_ok_at": (NOW - ok_age).isoformat(),
                 "attempted_at": (NOW - attempt_age).isoformat()}]

    recent = state(timedelta(days=29, hours=23), timedelta(hours=2))
    expired = state(timedelta(days=30), timedelta(hours=2))
    retry = state(timedelta(days=31), timedelta(minutes=59))
    assert not collector._due(recent, "sales", NOW, historical=True)
    assert collector._due(expired, "sales", NOW, historical=True)
    assert not collector._due(retry, "sales", NOW, historical=True)
    assert collector._due(recent, "sales", NOW, historical=False)
    assert collector._due([], "sales", NOW, historical=True)

    partial_history = [{
        "kind": "sales", "last_ok_at": None,
        "attempted_at": (NOW - timedelta(days=2)).isoformat(),
        "error_code": "incomplete_response",
    }]
    partial_current = [{
        "kind": "sales", "last_ok_at": None,
        "attempted_at": (NOW - timedelta(hours=2)).isoformat(),
        "error_code": "incomplete_response",
    }]
    invalid_history = [{**partial_history[0], "error_code": "source_shape"}]
    assert not collector._due(partial_history, "sales", NOW, historical=True)
    assert not collector._due(partial_current, "sales", NOW, historical=False)
    assert collector._due(invalid_history, "sales", NOW, historical=True)
