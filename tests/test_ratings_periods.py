"""Период отчёта (спека «Словарь»): месяц, квартал или период рейтинга РС."""

from __future__ import annotations

from datetime import date

from src.ratings.periods import (
    RatingPeriod,
    default_period,
    month_period,
    parse_period,
    previous_period,
    quarter_period,
)

РС = (
    RatingPeriod(
        11, date(2026, 9, 1), date(2026, 9, 15), "Сентябрь 1 часть 2026", "September part 1 2026"
    ),
    RatingPeriod(
        12, date(2026, 9, 16), date(2026, 9, 30), "Сентябрь 2 часть 2026", "September part 2 2026"
    ),
)


def test_квартал_и_месяц_по_ключу() -> None:
    q = parse_period("2026-Q3", rs_periods=РС)
    assert q is not None and (q.begin, q.end) == (date(2026, 7, 1), date(2026, 9, 30))
    m = parse_period("2026-02", rs_periods=РС)
    assert m is not None and m.end == date(2026, 2, 28)


def test_период_рейтинга_по_ключу() -> None:
    p = parse_period("rs:12", rs_periods=РС)
    assert p is not None and (p.begin, p.end, p.kind) == (
        date(2026, 9, 16),
        date(2026, 9, 30),
        "rating",
    )


def test_мусорный_ключ_нет() -> None:
    for key in ("2026-Q5", "2026-13", "rs:999", "rs:x", "вчера", ""):
        assert parse_period(key, rs_periods=РС) is None


def test_год_ноль_и_нечестные_цифры_нет() -> None:
    for key in ("0000-01", "0000-Q1", "2026-09\n", "2026-Q3\n", "rs:12\n", "٢٠٢٦-٠٩", "rs:١٢"):
        assert parse_period(key, rs_periods=РС) is None


def test_прошлый_у_первого_периода_эры_нет() -> None:
    assert previous_period(month_period(1, 1), rs_periods=РС) is None
    assert previous_period(quarter_period(1, 1), rs_periods=РС) is None
    assert previous_period(month_period(1, 2), rs_periods=РС) == month_period(1, 1)


def test_прошлый_такой_же_период() -> None:
    assert previous_period(quarter_period(2026, 1), rs_periods=РС) == quarter_period(2025, 4)
    assert previous_period(month_period(2026, 1), rs_periods=РС) == month_period(2025, 12)
    prev = previous_period(parse_period("rs:12", rs_periods=РС), rs_periods=РС)  # type: ignore[arg-type]
    assert prev is not None and prev.key == "rs:11"
    assert previous_period(parse_period("rs:11", rs_periods=РС), rs_periods=РС) is None  # type: ignore[arg-type]


def test_прошлый_период_рейтинга_ближайший_а_не_первый() -> None:
    август = RatingPeriod(10, date(2026, 8, 16), date(2026, 8, 31), "Август", "August")
    все = (август, *РС)
    текущий = parse_period("rs:12", rs_periods=все)
    assert текущий is not None
    prev = previous_period(текущий, rs_periods=все)
    assert prev is not None and prev.key == "rs:11"


def test_по_умолчанию_квартал_последних_данных() -> None:
    assert default_period(date(2026, 9, 16), today=date(2026, 10, 8)).key == "2026-Q3"
    assert default_period(None, today=date(2026, 10, 8)).key == "2026-Q4"
