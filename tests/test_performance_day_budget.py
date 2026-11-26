from datetime import UTC, date, datetime

from src.dodois import performance as collector
from src.domain.performance import Window
from tests.test_performance_collector import A, login


def test_single_day_metrics_stop_at_shared_budget_without_requesting_monthly_values(monkeypatch):
    seen, recorded = [], []
    monkeypatch.setattr(
        collector.logins, "read_tokens", lambda _: collector.logins.Tokens("x", "x")
    )
    monkeypatch.setattr(collector.client, "working_pizzerias", lambda _: [A])
    monkeypatch.setattr(collector.metrics_store, "country_units", lambda _: [A])
    monkeypatch.setattr(collector.store, "load_states", lambda *_: [])
    monkeypatch.setattr(
        collector.store, "record_load", lambda *args, **kwargs: recorded.append(kwargs)
    )

    def save(kind, _login, _token, _units, _active, period, _zone, throttle, **_kwargs):
        throttle.budget.charge()
        seen.append((kind, period))
        return 1

    monkeypatch.setattr(collector, "_save_kind", save)
    budget = collector.Budget(2)
    rows = collector.collect_metric_days(
        login(),
        Window(date(2026, 11, 1), date(2026, 11, 3)),
        budget=budget,
        now=datetime(2026, 11, 24, tzinfo=UTC),
    )
    assert budget.remaining == 0 and len(rows) == 1
    assert seen == [("delivery", Window(date(2026, 11, 3), date(2026, 11, 3)))]
    assert recorded[-1]["error_code"] == "request_budget"
