"""Числа истории: взвешенное среднее, пустые периоды и границы доступа экрана."""

from datetime import date

import pytest
from ratings_page import клиент, подготовить

from src.db.inspection_timeline import Month
from src.web import inspection_timeline as timeline

TODAY = date(2026, 10, 30)
ROWS = (
    Month(date(2024, 1, 1), 1, 80.0),
    Month(date(2024, 3, 1), 3, 300.0),
    Month(date(2026, 9, 1), 1, 93.5),
)


def test_years_weight_by_inspections_and_keep_empty_year() -> None:
    view = timeline.build(ROWS, {}, today=TODAY)
    assert view.years == (2024, 2025, 2026)
    assert [(b.count, b.average) for b in view.buckets] == [(4, 95.0), (0, None), (1, 93.5)]
    assert view.count == 5
    assert view.average == 94.7
    assert view.buckets[1].average is None


def test_months_keep_gaps_and_never_average_monthly_averages() -> None:
    view = timeline.build(ROWS, {"history_grain": "month", "history_year": "2024"}, today=TODAY)
    assert len(view.buckets) == 12
    assert view.count == 4
    assert view.average == 95.0
    assert view.buckets[1].count == 0
    assert view.buckets[1].average is None
    assert view.buckets[2].average == 100.0


@pytest.mark.parametrize("year", ["bogus", "9999", "٢٠٢٤", "9" * 5000])
def test_invalid_year_is_bounded(year: str) -> None:
    view = timeline.build(ROWS, {"history_grain": "month", "history_year": year}, today=TODAY)
    assert view.year == 2026


def test_empty_history_has_no_fictitious_zero_score() -> None:
    view = timeline.build((), {}, today=TODAY)
    assert not view.buckets
    assert view.average is None
    assert not view.failed


def test_control_cannot_read_inspections_even_through_ratings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)

    def forbidden(**_kwargs: object) -> None:
        pytest.fail("Контроль не должен читать проверки")

    monkeypatch.setattr(timeline, "load", forbidden)
    for client in клиент(monkeypatch, role="control"):
        assert client.get("/ratings/inspections").status_code == 404
        assert b"/ratings/inspections?" not in client.get("/ratings").data


def test_ratings_history_uses_selected_countries_and_ignores_page_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = подготовить(monkeypatch)
    countries = []

    def days(**kwargs: object) -> tuple[Month, ...]:
        countries.append(kwargs["countries"])
        return ROWS

    monkeypatch.setattr(timeline.store, "days", days)
    for client in клиент(monkeypatch):
        response = client.get("/ratings/inspections?group=country&value=RS&period=2026-09")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "94.7" in html and "2024" in html
        assert "История проверок" in html
        assert 'name="history_grain"' in html
    assert countries == [("RS",)]
    assert not calls["build"]


def test_exact_dates_survive_year_aggregation() -> None:
    from src.db.inspection_timeline import Day

    rows = (
        Day(date(2026, 1, 5), 1, 81.0),
        Day(date(2026, 6, 1), 1, 90.0),
        Day(date(2026, 10, 1), 1, 96.0),
    )
    view = timeline.build(rows, {}, today=TODAY)
    assert len(view.buckets) == 1
    assert [p.day for p in view.points] == [r.start for r in rows]
    assert [p.average for p in view.points] == [81.0, 90.0, 96.0]
    assert view.points[0].x < view.points[1].x < view.points[2].x
    assert view.points[0].y > view.points[1].y > view.points[2].y


def test_same_day_is_weighted_and_single_date_is_centered() -> None:
    from src.db.inspection_timeline import Day

    view = timeline.build(
        (Day(date(2026, 9, 1), 1, 80.0), Day(date(2026, 9, 1), 3, 300.0)), {}, today=TODAY
    )
    assert len(view.points) == 1
    assert view.points[0].count == 4
    assert view.points[0].average == 95.0
    assert view.points[0].x == 0.5


def test_month_view_filters_primary_dates_to_selected_year() -> None:
    view = timeline.build(ROWS, {"history_grain": "month", "history_year": "2024"}, today=TODAY)
    assert all(p.day.year == 2024 for p in view.points)
    assert len(view.points) == 2
