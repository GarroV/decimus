"""Клиентские оценки: вес, период, реальные состояния загрузки и настоящий HTML."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.db import customer_ratings as read
from src.db.customer_ratings import KrLoad, MonthlyKr
from src.db.errors import RatingsError
from src.ratings import clients
from src.web import ratings_clients


def row(unit="a", month=date(2026, 10, 1), average="5", count=1, country="RS"):
    return MonthlyKr(country, unit, f"Pizzeria {unit}", month, Decimal(average), count, None, 0)


def test_quarter_weights_units_and_months_by_review_count():
    rows = [
        row(average="5", count=1),
        row(month=date(2026, 11, 1), average="1", count=9),
        row("b", average="4", count=90),
    ]
    result = clients.aggregate("", "", "", rows)
    assert result.total == clients.Score(Decimal("3.74"), 100)
    units = clients.units(rows)
    assert units[0].total == clients.Score(Decimal("1.4"), 10)
    assert units[1].total == clients.Score(Decimal("4"), 90)


def test_unknown_average_keeps_count_and_does_not_report_biased_average():
    assert clients.weighted([(Decimal(5), 3), (None, 2)]) == clients.Score(None, 5)
    assert clients.weighted([(None, 0)]) == clients.Score(None, 0)


@pytest.mark.parametrize(
    ("begin", "end", "today", "expected"),
    [
        (
            date(2026, 10, 1),
            date(2026, 12, 31),
            date(2027, 1, 1),
            (date(2026, 10, 1), date(2026, 12, 1)),
        ),
        (
            date(2026, 10, 15),
            date(2026, 11, 15),
            date(2026, 12, 1),
            (date(2026, 11, 1), date(2026, 10, 1)),
        ),
        (
            date(2026, 10, 1),
            date(2026, 11, 2),
            date(2026, 11, 2),
            (date(2026, 10, 1), date(2026, 11, 1)),
        ),
        (
            date(2026, 10, 2),
            date(2026, 10, 15),
            date(2026, 11, 2),
            (date(2026, 11, 1), date(2026, 9, 1)),
        ),
    ],
)
def test_month_coverage_does_not_invent_daily_data(begin, end, today, expected):
    assert clients.coverage(begin, end, today) == expected


def source(monkeypatch, rows, states=None, latest=date(2026, 10, 1)):
    monkeypatch.setattr(read, "monthly", lambda *_: rows)
    monkeypatch.setattr(read, "loads", lambda *_: states or [])
    monkeypatch.setattr(read, "latest_month", lambda *_: latest)


def test_collection_failure_does_not_hide_saved_scores(monkeypatch):
    source(monkeypatch, [row()], [KrLoad("RS", datetime.now(UTC), True)])
    view = ratings_clients.load(
        ("RS",), date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 11, 2)
    )
    assert view.failed and view.status == "stale"
    assert view.total.total.count == 1


def test_db_failure_is_distinct_from_empty_data(monkeypatch):
    def fail(*_):
        raise RatingsError("synthetic unavailable")

    monkeypatch.setattr(read, "monthly", fail)
    view = ratings_clients.load(
        ("RS",), date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 11, 2)
    )
    assert view.failed
    assert view.units == ()


def test_real_page_renders_existing_month_and_weights_not_placeholder(monkeypatch):
    from ratings_page import подготовить, получить

    подготовить(monkeypatch)
    source(
        monkeypatch,
        [row(average="5", count=1), row("b", average="1", count=9)],
        [KrLoad("RS", datetime.now(UTC), False)],
    )
    html = получить(monkeypatch, "/ratings/clients?group=country&value=RS&period=2026-Q4")
    assert "1.40" in html and "Оценок: 10" in html
    assert "Pizzeria a" in html and "Pizzeria b" in html
    assert "Месяцы с оценками" in html
    assert "появятся после подключения" not in html


def test_empty_current_period_links_to_existing_month(monkeypatch):
    from ratings_page import подготовить, получить

    подготовить(monkeypatch)
    source(monkeypatch, [], [], date(2026, 10, 1))
    html = получить(monkeypatch, "/ratings/clients?group=country&value=RS&period=2026-11")
    assert "Открыть последний месяц с данными: 2026-10" in html
    assert "period=2026-10" in html


def test_db_read_scopes_all_countries_and_boundaries_in_one_query(monkeypatch):
    calls = []
    monkeypatch.setattr(read, "_unit_rows", lambda sql, params: calls.append((sql, params)) or [])
    assert read.monthly(("BG", "RS"), date(2026, 10, 1), date(2026, 12, 1)) == []
    assert len(calls) == 1
    assert calls[0][1] == (["BG", "RS"], date(2026, 10, 1), date(2026, 12, 1))
    assert "country_code=any(%s)" in calls[0][0]


def test_metadata_failure_preserves_already_read_customer_scores(monkeypatch):
    source(monkeypatch, [row()])

    def fail(*_):
        raise RatingsError("synthetic")

    monkeypatch.setattr(read, "loads", fail)
    view = ratings_clients.load(
        ("RS",), date(2026, 10, 1), date(2026, 10, 31), today=date(2026, 11, 2)
    )
    assert view.failed and view.total.total.count == 1
    assert view.units[0].name == "Pizzeria a"


def test_current_month_coverage_does_not_claim_today_has_been_collected(monkeypatch):
    source(monkeypatch, [row(month=date(2026, 11, 1))])
    view = ratings_clients.load(
        ("RS",), date(2026, 11, 1), date(2026, 11, 30), today=date(2026, 11, 2)
    )
    assert view.begin == date(2026, 11, 1)
    assert view.end == date(2026, 11, 1)
