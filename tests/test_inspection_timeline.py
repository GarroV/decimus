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


def _tip_days() -> tuple:
    from src.db.inspection_timeline import Day, Item

    many = tuple(Item(f"{i:032x}", f"Belgrade-{i}", "RS", "planned", 80.0 + i) for i in range(1, 9))
    return (
        Day(date(2026, 9, 1), 1, 86.0, (Item("a" * 32, "Batumi-1", "GE", "repeat", 86.0),)),
        Day(date(2026, 10, 15), 10, 850.0, many),
    )


def test_point_details_carry_unit_country_kind_and_score_in_the_page_language() -> None:
    ru = timeline.build(_tip_days(), {}, today=TODAY, lang="ru")
    en = timeline.build(_tip_days(), {}, today=TODAY, lang="en")
    first = ru.points[0].details[0]
    assert (first.unit, first.country, first.kind, first.pct) == (
        "Batumi-1",
        "Грузия",
        "Повторная",
        86.0,
    )
    assert en.points[0].details[0].country == "Georgia"
    assert en.points[0].details[0].kind != first.kind
    # Точка-сводка: средняя по всем десяти, подробности — только первые, остальное считается числом.
    assert ru.points[1].count == 10 and len(ru.points[1].details) == 8


def test_unknown_kind_code_is_shown_as_is_not_dropped() -> None:
    from src.db.inspection_timeline import Day, Item

    view = timeline.build(
        (Day(date(2026, 9, 1), 1, 80.0, (Item("b" * 32, "X-1", "GE", "mystery", 80.0),)),),
        {},
        today=TODAY,
    )
    assert view.points[0].details[0].kind == "mystery"


def test_graph_tooltip_and_dense_top_on_the_ratings_inspections_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    monkeypatch.setattr(timeline.store, "days", lambda **_kw: _tip_days())
    for client in клиент(monkeypatch):
        html = client.get("/ratings/inspections?group=country&value=RS").get_data(as_text=True)
    # Подсказка точки: пиццерия ссылкой на проверку, страна, вид, результат, дата.
    assert 'class="ih-pt' in html and 'role="tooltip"' in html
    assert f'href="/inspections/{"a" * 32}"' in html
    assert "Batumi-1" in html and "Грузия" in html and "Повторная" in html
    assert "86.0" in html and "01.09.2026" in html
    # Больше восьми — «и ещё N»; на телефоне строк меньше, поэтому и N больше.
    assert "и ещё 2" in html and "и ещё 5" in html
    # Плотный верх: «Мои страны / Все страны» — меню в строке фильтров, а не отдельный ряд;
    # группировка применяется сразу, кнопка «Показать» — только без скриптов.
    assert 'class="cstrip"' in html and 'class="cscope pick"' in html
    assert "rt-personal" not in html and "rt-controls" in html
    assert "<noscript><button" in html and "data-history-auto" in html
    assert "Выбрать мои страны…" in html
    # Пояснение блока — под «?», а не абзацем над формой.
    assert 'class="pk-empty pk-empty--pad">Вся история' not in html
    assert "Вся история принятых проверок" in html
