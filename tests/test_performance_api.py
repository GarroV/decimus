"""Поверхность performance: чтение кеша, отдельное право и охват стран."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from flask import Flask

from src.db import api_access, performance, ratings_read
from src.db.errors import DbError
from src.domain.performance import Observation, Window
from src.web import swarm_api
from src.web.config import Settings


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True)
    swarm_api.install(
        app,
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant="HQ",
            ui_lang="en",
            secret_key="test-secret-is-long-enough-for-this-fixture",
        ),
    )
    monkeypatch.setattr(
        swarm_api,
        "_identify",
        lambda _: api_access.ApiToken(
            1, "test", (api_access.SCOPE_PERFORMANCE,), countries=("RS",)
        ),
    )
    monkeypatch.setattr(api_access, "recent_requests", lambda *_: 0)
    monkeypatch.setattr(api_access, "log_access", lambda *_: None)
    monkeypatch.setattr(
        ratings_read,
        "countries",
        lambda: (ratings_read.CountryRow("RS", "Сербия", "Serbia", None, True),),
    )
    monkeypatch.setattr(performance, "unit_names", lambda _: {"aa" * 16: ("RS", "Testville-1")})
    monkeypatch.setattr(
        performance,
        "read_observations",
        lambda *_: [
            Observation(
                "RS",
                "RS",
                "revenue",
                Window(date(2026, 11, 1), date(2026, 11, 15)),
                value=Decimal("12345.67"),
                currency="RSD",
                covered_units=1,
                expected_units=1,
                loaded_at=datetime(2026, 11, 16, tzinfo=UTC),
            )
        ],
    )
    monkeypatch.setattr(performance, "read_lfl", lambda *_: [])
    monkeypatch.setattr(performance, "load_states", lambda *_: [])
    return app.test_client()


def test_read_cached_exact_window(client):
    response = client.get("/api/v1/performance?as_of=2026-11-15")
    assert response.status_code == 200
    country = response.json["countries"][0]
    assert country["cc"] == "RS" and country["name"] == "Serbia"
    assert country["periods"]["current"] == {"from": "2026-11-01", "to": "2026-11-15"}
    assert country["metrics"]["revenue"]["current"]["value"] == "12345.67"
    assert country["metrics"]["revenue"]["yoy"]["delta_pct"] is None
    assert country["units"][0]["name"] == "Testville-1"
    assert response.headers["Vary"] == "Authorization"


def test_existing_sales_scope_does_not_grant_performance(client, monkeypatch):
    monkeypatch.setattr(
        swarm_api, "_identify", lambda _: api_access.ApiToken(1, "test", (api_access.SCOPE_SALES,))
    )
    assert client.get("/api/v1/performance?as_of=2026-11-15").status_code == 403


def test_country_grant_cannot_be_widened(client):
    response = client.get("/api/v1/performance?countries=BG&as_of=2026-11-15")
    assert response.status_code == 403
    assert response.json["error"] == "forbidden_country"


def test_reject_invalid_and_incomplete_days(client):
    assert client.get("/api/v1/performance?as_of=2026-11-31").status_code == 400
    response = client.get("/api/v1/performance?as_of=2999-01-01")
    assert response.status_code == 400 and response.json["error"] == "incomplete_day"


def test_database_failure_is_not_empty_country(client, monkeypatch):
    def failed(*_):
        raise DbError("database failed")

    monkeypatch.setattr(performance, "read_observations", failed)
    response = client.get("/api/v1/performance?as_of=2026-11-15")
    assert response.status_code == 503
    assert response.json["error"] == "db_unavailable"
