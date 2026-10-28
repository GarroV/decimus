"""Экран «Качество»: доступ, охват партнёра, честные пустые состояния, вывод цифр.

База не нужна: чтения подменены на границах модулей-источников. Формулы проверяет
`tests/test_quality.py`; здесь — что экран собирает входы и показывает числа ядра.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal as D

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import agg_store, dodois_logins, dodois_metrics, maps_store, quality_read
from src.db import ratings_read as read
from src.db.reach import Reach
from src.web import ratings_freshness

MONTH = date(2026, 9, 1)
PL1, PL2 = "a" * 32, "b" * 32
BG1 = "c" * 32


def _countries() -> tuple[read.CountryRow, ...]:
    return (
        read.CountryRow("PL", "Польша", "Poland", None, True),
        read.CountryRow("BG", "Болгария", "Bulgaria", None, True),
        read.CountryRow("RU", "Россия", "Russia", None, False),
    )


def _scores(countries: object, month: date) -> tuple[quality_read.PeriodScore, ...]:
    if month != MONTH:
        return ()
    rows = []
    for unit, name, country, rko, rs in (
        (PL1, "Warsaw-1", "PL", "90.89", "92"),
        (PL2, "Krakow-1", "PL", "80", "85"),
        (BG1, "Sofia-1", "BG", "95", "90"),
    ):
        rows.append(quality_read.PeriodScore(unit, name, country, "rko", D(rko), 5, None))
        rows.append(quality_read.PeriodScore(unit, name, country, "rs", D(rs), None, None))
    return tuple(rows)


def _poland_sales(code: str, month: date) -> list[dodois_metrics.UnitSales]:
    if code != "PL" or month != MONTH:
        return []
    return [
        dodois_metrics.UnitSales(PL1, "Aggregator", "Delivery", 35, D("3500"), "PLN"),
        dodois_metrics.UnitSales(PL1, "MobileApp", "Delivery", 25, D("2500"), "PLN"),
        dodois_metrics.UnitSales(PL1, "Dine-in", "Dine-in", 40, D("4000"), "PLN"),
    ]


@pytest.fixture
def чтения(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(read, "countries", _countries)
    monkeypatch.setattr(read, "period_months", lambda: (MONTH,))
    monkeypatch.setattr(quality_read, "period_scores", _scores)
    monkeypatch.setattr(quality_read, "audit_pcts", lambda reach, countries, month: {PL1: D("90")})
    monkeypatch.setattr(
        maps_store,
        "unit_scores_dated",
        lambda provider, until: {PL1: (4.38, 100, date(2026, 9, 20))} if provider == 2 else {},
    )
    monkeypatch.setattr(agg_store, "units", lambda countries=None: ())
    monkeypatch.setattr(
        agg_store,
        "latest",
        lambda countries, until=None: (
            agg_store.LatestRating("PL", "wolt", PL1, 8.2, 10, 50, date(2026, 9, 25)),
        ),
    )
    monkeypatch.setattr(dodois_logins, "list_logins", lambda: ())
    monkeypatch.setattr(dodois_metrics, "unit_sales", _poland_sales)
    monkeypatch.setattr(
        dodois_metrics,
        "unit_aggregator_orders",
        lambda code, month: (
            [
                dodois_metrics.UnitAggregatorOrders(PL1, "Wolt", 30, D("3000")),
                dodois_metrics.UnitAggregatorOrders(PL1, "Pyszne", 5, D("500")),
            ]
            if code == "PL" and month == MONTH
            else []
        ),
    )
    monkeypatch.setattr(
        dodois_metrics,
        "unit_kr",
        lambda code, month: (
            [dodois_metrics.UnitKr(PL1, D("4.6"), 10, D("4.7"), 30)]
            if code == "PL" and month == MONTH
            else []
        ),
    )
    monkeypatch.setattr(dodois_metrics, "load_states", lambda: [])
    monkeypatch.setattr(ratings_freshness, "build", lambda *_a, **_k: None)


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant: str = "HQ",
    role: str | None = "admin",
    countries: tuple[str, ...] | None = None,
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    if countries is not None:
        monkeypatch.setattr("src.web.auth.reach_of", lambda t: Reach(t, None, countries))
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def ук(monkeypatch: pytest.MonkeyPatch, чтения: None) -> Iterator[FlaskClient]:
    yield from _client(monkeypatch)


def test_network_summary_ranks_countries_and_skips_non_imf(ук: FlaskClient) -> None:
    html = ук.get("/quality?month=2026-09").get_data(as_text=True)
    assert "Poland" not in html and "Польша" in html and "Болгария" in html
    assert "Россия" not in html
    # Польша имеет ЛКО (РКО, карты, агрегаторы, КР), Болгария — тоже; сводка со страницы сети
    assert "Все страны" in html and "country=PL" in html


def test_country_page_shows_all_blocks_and_core_numbers(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)
    for block in (
        "Из чего складывается ЛКО",
        "Каналы заказов",
        "Выручка по каналам продаж",
        "Клиентский рейтинг",
        "Карты",
    ):
        assert block in html, block
    assert "Warsaw-1" in html and "Krakow-1" in html
    assert "PLN" in html and "Зал" in html and "Доставка" in html
    assert "4.68" in html or "4.67" in html  # КР: (4.6*10 + 4.7*30) / 40, не прочерк
    assert "Wolt" in html and "Pyszne" in html


def test_country_without_dodois_says_it_is_not_connected(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=BG&month=2026-09").get_data(as_text=True)
    assert "страна не подключена" in html
    assert "Sofia-1" in html
    # сумма весов меньше 100% — пометка, а не пересчёт
    assert "Сумма весов" in html


def test_month_without_data_is_an_honest_empty_state(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-08").get_data(as_text=True)
    assert "нет данных качества" in html


def test_foreign_country_is_404(ук: FlaskClient) -> None:
    assert ук.get("/quality?country=RU").status_code == 404


def test_english_texts_exist(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09&lang=en").get_data(as_text=True)
    assert "Order channels" in html and "Revenue by sales channel" in html


def test_partner_sees_only_own_countries(monkeypatch: pytest.MonkeyPatch, чтения: None) -> None:
    for client in _client(monkeypatch, tenant="LV", role="admin", countries=("PL",)):
        html = client.get("/quality?month=2026-09").get_data(as_text=True)
        assert "Польша" in html and "Болгария" not in html
        assert client.get("/quality?country=BG").status_code == 404


def test_database_failure_shows_message_not_traceback(
    monkeypatch: pytest.MonkeyPatch, ук: FlaskClient
) -> None:
    from src.db.errors import RatingsError

    def boom(*_a: object, **_k: object) -> None:
        raise RatingsError("down")

    monkeypatch.setattr(quality_read, "period_scores", boom)
    response = ук.get("/quality?month=2026-09")
    assert response.status_code == 200
    assert "не прочитались" in response.get_data(as_text=True)


def test_dodois_not_collected_for_connected_country(
    monkeypatch: pytest.MonkeyPatch, ук: FlaskClient
) -> None:
    login = type("L", (), {"country": "BG"})()
    monkeypatch.setattr(dodois_logins, "list_logins", lambda: (login,))
    html = ук.get("/quality?country=BG&month=2026-09").get_data(as_text=True)
    assert "ещё не собраны" in html
