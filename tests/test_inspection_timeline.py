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
    assert view.buckets[1].score_y is None


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

    def months(**kwargs: object) -> tuple[Month, ...]:
        countries.append(kwargs["countries"])
        return ROWS

    monkeypatch.setattr(timeline.store, "months", months)
    for client in клиент(monkeypatch):
        response = client.get("/ratings/inspections?group=country&value=RS&period=2026-09")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "94.7" in html and "2024" in html
        assert "История проверок" in html
        assert 'name="history_grain"' in html
    assert countries == [("RS",)]
    assert not calls["build"]
