"""Экран «Качество»: доступ, охват партнёра, честные пустые состояния, вывод цифр.

База не нужна: чтения подменены на границах модулей-источников. Формулы проверяет
`tests/test_quality.py`; здесь — что экран собирает входы и показывает числа ядра.
"""

from __future__ import annotations

import re
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
    monkeypatch.setattr(dodois_metrics, "months_with_data", lambda code: [MONTH])
    monkeypatch.setattr(dodois_metrics, "unit_rating_periods", lambda code, month: [])
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


def test_network_table_has_one_row_per_country_and_skips_non_imf(ук: FlaskClient) -> None:
    html = ук.get("/quality?month=2026-09").get_data(as_text=True)
    assert "Poland" not in html and "Польша" in html and "Болгария" in html
    assert "Россия" not in html
    assert "Все страны" in html and "country=PL" in html
    # Сеть — как прототип аналитика (D722): оценка рядом с весом, без РС, выручки и проверки.
    head = html[html.index("<thead>") : html.index("</thead>")]
    top, bottom = head.split("</tr>")[:2]
    pick = r"<a class=\"qa-sort\"[^>]*>([^<]+?)(?: [▲▼])?</a>"
    assert re.findall(pick, top) == ["Страна", "Рейтинг, из 5"]  # на оба этажа
    assert re.findall(pick, bottom) == [
        "РКО, из 100",
        "РКО adj, из 5",
        "Проверок в нед.",
        "Вес",
        "Оценка",
        "Вес",
        "Оценка (G/Y)",
        "Вес (20%)",
        "Оценка",
        "Вес",
        "Агрегаторы",
        "Приложение и сайт",
        "Прочее",
    ]
    for group in ("РКО", "КР", "Карты", "Агрегаторы", "Доли заказов"):
        assert f'class="qa-group qa-edge">{group}<' in head, group
    for gone in ("РС", "Зал", "Доставка", "Проверка", "Выручка"):
        assert gone not in head, gone


def test_country_page_shows_all_blocks_and_core_numbers(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)
    for block in (
        "Пиццерии",
        "Агрегаторы",
        "Выручка",
        "Источник заказа",
        "Клиентский рейтинг",
        "Карты",
        "Периоды РКО и РС",
    ):
        assert block in html, block
    assert "Warsaw-1" in html and "Krakow-1" in html
    assert "PLN" in html and "Зал" in html and "Доставка" in html
    assert "4.68" in html or "4.67" in html  # КР: (4.6*10 + 4.7*30) / 40, не прочерк
    assert "Wolt" in html and "Pyszne" in html
    assert "Приложение" in html  # источник заказа переведён, а не «MobileApp»


def test_country_without_dodois_says_it_is_not_connected(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=BG&month=2026-09").get_data(as_text=True)
    assert "страна не подключена" in html
    assert "Sofia-1" in html


def test_no_composite_score_or_ranking_anywhere(ук: FlaskClient) -> None:
    """D677/D719: ни ЛКО, ни ЭС, ни «Общего рейтинга», ни мест — на обоих языках."""
    banned = ("ЛКО", "ЭС", "LKO", "Лучший клиентский", "Эталон стандартов", "Общий рейтинг")
    for url in (
        "/quality?month=2026-09",
        "/quality?country=PL&month=2026-09",
        "/quality?month=2026-09&lang=en",
        "/quality?country=PL&month=2026-09&lang=en",
    ):
        html = ук.get(url).get_data(as_text=True)
        for word in banned:
            assert word not in html, (url, word)
        assert "место" not in html


def test_country_page_shows_total_weights_and_how_it_is_computed(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)

    assert "Рейтинг, из 5" in html and "Вес (20%)" in html and ">Веса<" not in html
    assert "по её строке" in html  # итог страны — по строке страны (D722)
    assert "Как считается итог" in html
    # Пороги веса РКО и вес карт — из констант, словами.
    assert "нет проверок — 0%" in html and "меньше 2 — 10%" in html
    assert "меньше 5 — 30%" in html and "5 и больше — 50%" in html
    assert "Вес карт — 20%" in html and "делится на 20" in html
    # Веса пиццерии в процентах целыми: у Warsaw-1 есть карты, КР и агрегаторы.
    assert "20%" in html and "Итог " in html  # колонка стран слева: «Итог … · РКО … · РС …»
    en = ук.get("/quality?country=PL&month=2026-09&lang=en").get_data(as_text=True)
    assert "How the total is computed" in en and "Rating, of 5" in en
    assert "from its own row" in en and "Weight (20%)" in en


def test_total_column_sorts(ук: FlaskClient) -> None:
    assert ук.get("/quality?country=PL&month=2026-09&sort=total&dir=desc").status_code == 200
    assert ук.get("/quality?month=2026-09&sort=w_kr&dir=asc").status_code == 200


def test_rko_below_thresholds_is_tinted_like_ratings(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)

    assert "qa-tone--mid" in html  # Krakow-1: РКО 80 — жёлтая зона (80–90)
    assert "qa-tone--bad" not in html  # красного (ниже 80) здесь нет


def test_units_sort_by_column_with_missing_values_last(ук: FlaskClient) -> None:
    desc = ук.get("/quality?country=PL&month=2026-09&sort=rko&dir=desc").get_data(as_text=True)
    asc = ук.get("/quality?country=PL&month=2026-09&sort=rko&dir=asc").get_data(as_text=True)

    assert desc.index("Warsaw-1") < desc.index("Krakow-1")  # РКО 90.89 против 80
    assert asc.index("Krakow-1") < asc.index("Warsaw-1")
    assert "aria-sort" in desc


def test_month_without_data_is_an_honest_empty_state(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-08").get_data(as_text=True)
    assert "нет данных качества" in html


def test_default_month_is_the_current_one_and_marked_in_progress(ук: FlaskClient) -> None:
    html = ук.get("/quality").get_data(as_text=True)

    assert "месяц идёт" in html
    assert f"?month={date.today():%Y-%m}" in html or f"month={date.today():%Y-%m}" in html


def test_past_month_is_not_marked_in_progress(ук: FlaskClient) -> None:
    html = ук.get("/quality?month=2026-09").get_data(as_text=True)

    # Выбран прошлый месяц: пометка только у текущего в списке выбора.
    assert html.count("месяц идёт") == 1


def test_foreign_country_is_404(ук: FlaskClient) -> None:
    assert ук.get("/quality?country=RU").status_code == 404


def test_rko_month_rule_is_explained_under_the_question_mark(ук: FlaskClient) -> None:
    ru = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)
    en = ук.get("/quality?country=PL&month=2026-09&lang=en").get_data(as_text=True)
    assert "РКО за месяц — все недели (пн–вс), у которых хоть один день в этом месяце" in ru
    assert "неделя на стыке входит в оба месяца" in ru
    assert "RKO for a month — every week (Mon–Sun) with at least one day" in en


def test_english_texts_exist(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09&lang=en").get_data(as_text=True)
    assert "Order source" in html and "Pizzerias" in html and "Revenue" in html


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


def test_quality_renders_on_demo_stand_without_dodois_data(
    monkeypatch: pytest.MonkeyPatch, чтения: None
) -> None:
    # Демо: данных Dodo IS нет (сборщик на демо не засеян), рейтинги и карты — как есть.
    monkeypatch.setattr(dodois_metrics, "unit_sales", lambda code, month: [])
    monkeypatch.setattr(dodois_metrics, "unit_aggregator_orders", lambda code, month: [])
    monkeypatch.setattr(dodois_metrics, "unit_kr", lambda code, month: [])
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ", demo=True).test_client() as client:
        assert войти(client).status_code == 302
        for url in ("/quality", "/quality?country=PL", "/quality?country=BG&month=2026-09"):
            response = client.get(url)
            assert response.status_code == 200, url
            assert "не прочитались" not in response.get_data(as_text=True), url


def test_empty_later_month_links_to_saved_data_without_changing_default(
    ук: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def latest(countries):
        calls.append(tuple(countries))
        return MONTH

    monkeypatch.setattr(dodois_metrics, "latest_available_month", latest)
    response = ук.get("/quality?country=PL&month=2026-10&lang=ru")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Последний месяц с сохранёнными данными Dodo IS" in html
    assert "month=2026-09" in html
    assert calls == [("PL",)]


BG2, BG3 = "d" * 32, "e" * 32


def _registry_only_units(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пиццерии BG2 и BG3 есть только в реестре; за месяц у них лишь оценки агрегатора и карт."""
    monkeypatch.setattr(
        agg_store,
        "units",
        lambda countries=None: (
            agg_store.UnitRow(BG2, "BG", "Plovdiv-1", 0.0, 0.0, True, MONTH, MONTH),
            agg_store.UnitRow(BG3, "BG", "Varna-1", 0.0, 0.0, True, MONTH, MONTH),
        ),
    )
    monkeypatch.setattr(
        agg_store,
        "latest",
        lambda countries, until=None: (
            agg_store.LatestRating("BG", "glovo", BG2, 9.0, 10, 20, date(2026, 9, 25)),
        ),
    )
    monkeypatch.setattr(
        maps_store,
        "unit_scores_dated",
        lambda provider, until: {BG3: (4.2, 40, date(2026, 9, 20))} if provider == 2 else {},
    )


def test_unit_with_only_aggregator_or_map_rating_is_not_lost(
    monkeypatch: pytest.MonkeyPatch, чтения: None
) -> None:
    from src.web import quality_data

    _registry_only_units(monkeypatch)
    found = quality_data.load_month(Reach("HQ", None, ("BG",)), ("BG",), MONTH)["BG"]
    by_name = {u.name: u for u in found.units}

    assert {"Sofia-1", "Plovdiv-1", "Varna-1"} <= set(by_name)
    assert by_name["Plovdiv-1"].values["aggs"] == D("4.5")  # 9 из 10 → 4.5 из 5
    assert by_name["Varna-1"].values["maps"] == D("4.2")
    assert found.values["maps"] == D("4.2") and found.values["aggs"] == D("4.5")


def test_network_moves_countries_without_values_under_the_table(
    monkeypatch: pytest.MonkeyPatch, ук: FlaskClient
) -> None:
    monkeypatch.setattr(
        read,
        "countries",
        lambda: (*_countries(), read.CountryRow("SK", "Словакия", "Slovakia", None, True)),
    )
    html = ук.get("/quality?month=2026-09").get_data(as_text=True)
    table = html[html.index("<tbody>") : html.index("</tbody>")]

    assert "Польша" in table and "Болгария" in table  # есть РКО и РС
    assert "Словакия" not in table
    assert "Нет данных за сентябрь 2026 (1): " in html
    assert "qa-nodata" in html and "country=SK" in html.split("qa-nodata")[1]


def test_rail_says_pizzerias_count_when_country_has_units_but_no_rko_rs(
    monkeypatch: pytest.MonkeyPatch, чтения: None
) -> None:
    _registry_only_units(monkeypatch)
    monkeypatch.setattr(quality_read, "period_scores", lambda countries, month: ())
    html = next(_client(monkeypatch)).get("/quality?month=2026-09").get_data(as_text=True)

    assert "пиццерий: 2" in html  # BG: две пиццерии с одними оценками, РКО и РС нет


def test_header_has_two_floors_with_groups(ук: FlaskClient) -> None:
    html = ук.get("/quality?country=PL&month=2026-09").get_data(as_text=True)

    assert 'colspan="4"' in html and 'colspan="2"' in html and 'rowspan="2"' in html
    assert "qa-edge" in html
