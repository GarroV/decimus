"""Данные Dodo IS для «Качества» в настоящей базе (D671, миграция 0105): замена месяца, чтение.

Роль приложения пишет и читает; месяц заменяется целиком только у пиццерий, ответивших в заход;
страну чтение берёт соединением с `ratings.units`; свежесть и последняя ошибка — из журнала.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import dodois_metrics as read  # noqa: E402
from src.db import dodois_metrics_store as store  # noqa: E402
from src.domain.dodois_metrics import (  # noqa: E402
    AggregatorMonth,
    CheckupPeriod,
    KrRow,
    RatingPeriod,
    SalesRow,
)

pytestmark = requires_db

СЕНТЯБРЬ = date(2026, 9, 1)
ОКТЯБРЬ = date(2026, 10, 1)
А = "a" * 32  # BG
Б = "b" * 32  # BG
В = "c" * 32  # RS


@pytest.fixture
def пиццерии(db_env: str) -> str:
    with psycopg.connect(db_env) as conn:
        for код, имя in (("BG", "Bulgaria"), ("RS", "Serbia")):
            conn.execute(
                "insert into ratings.countries (code, name_ru, name_en) values (%s, %s, %s)",
                (код, имя, имя),
            )
        for dodo, страна in ((А, "BG"), (Б, "BG"), (В, "RS")):
            conn.execute(
                "insert into ratings.units (dodo_id, name, name_normalized, country_code) "
                "values (%s, %s, %s, %s)",
                (dodo, dodo[:3], dodo[:3], страна),
            )
        conn.commit()
    return db_env


def test_продажи_читаются_по_стране_и_месяцу(пиццерии: str) -> None:
    store.replace_sales(
        СЕНТЯБРЬ,
        [А, Б, В],
        [
            SalesRow(А, "Website", "Delivery", 10, Decimal("100.50"), "BGN"),
            SalesRow(В, "Kiosk", "Dine-in", 3, Decimal("30"), None),
        ],
    )

    найдено = read.unit_sales("BG", СЕНТЯБРЬ)

    assert найдено == [read.UnitSales(А, "Website", "Delivery", 10, Decimal("100.50"), "BGN")]
    assert read.unit_sales("BG", ОКТЯБРЬ) == []


def test_повторная_загрузка_заменяет_месяц_а_не_удваивает(пиццерии: str) -> None:
    store.replace_sales(СЕНТЯБРЬ, [А], [SalesRow(А, "Website", "Delivery", 10, Decimal(100), None)])
    store.replace_sales(СЕНТЯБРЬ, [А], [SalesRow(А, "Kiosk", "Dine-in", 4, Decimal(40), None)])

    assert [(r.order_source, r.orders) for r in read.unit_sales("BG", СЕНТЯБРЬ)] == [("Kiosk", 4)]


def test_пиццерия_вне_ответа_сохраняет_прежний_месяц(пиццерии: str) -> None:
    store.replace_sales(СЕНТЯБРЬ, [А, Б], [SalesRow(Б, "Kiosk", "Dine-in", 7, Decimal(70), None)])
    store.replace_sales(СЕНТЯБРЬ, [А], [SalesRow(А, "Website", "Delivery", 1, Decimal(1), None)])

    assert {r.dodo_id for r in read.unit_sales("BG", СЕНТЯБРЬ)} == {А, Б}


def test_агрегаторы_и_оценки_читаются(пиццерии: str) -> None:
    store.replace_aggregators(
        СЕНТЯБРЬ,
        [А],
        [
            AggregatorMonth(А, "Glovo", 5),
            AggregatorMonth(А, "Wolt", 1),
        ],
    )
    store.replace_kr(
        СЕНТЯБРЬ,
        [А, Б],
        [KrRow(А, Decimal("4.73"), 210, None, 0), KrRow(Б, None, 0, None, 0)],
    )

    assert [(r.aggregator, r.orders) for r in read.unit_aggregator_orders("BG", СЕНТЯБРЬ)] == [
        ("Glovo", 5),
        ("Wolt", 1),
    ]
    # Пиццерия без единой оценки строки не получает: «нет оценок» не равно «оценка ноль».
    assert read.unit_kr("BG", СЕНТЯБРЬ) == [read.UnitKr(А, Decimal("4.73"), 210, None, 0)]


def test_месяцы_с_данными_свежие_первыми_и_только_своей_страны(пиццерии: str) -> None:
    store.replace_sales(СЕНТЯБРЬ, [А], [SalesRow(А, "Kiosk", "Dine-in", 1, Decimal(1), None)])
    store.replace_kr(ОКТЯБРЬ, [Б], [KrRow(Б, Decimal(5), 1, None, 0)])
    store.replace_kr(date(2026, 8, 1), [В], [KrRow(В, Decimal(5), 1, None, 0)])

    assert read.months_with_data("BG") == [ОКТЯБРЬ, СЕНТЯБРЬ]
    assert read.months_with_data("RS") == [date(2026, 8, 1)]


def test_журнал_даёт_свежесть_и_последнюю_ошибку_по_стране(пиццерии: str) -> None:
    for вид in ("sales", "aggregators", "kr", "ratings"):
        номер = store.start_load("BG", вид)
        store.finish_load(номер, ok=True, rows=3)
    номер = store.start_load("BG", "kr")
    store.finish_load(номер, ok=False, error="rate_limited")
    номер = store.start_load("RS", "kr")
    store.finish_load(номер, ok=True, rows=1)

    состояния = {s.country_code: s for s in read.load_states()}

    assert состояния["BG"].last_ok_at is not None
    assert состояния["BG"].last_error == "rate_limited"
    assert состояния["RS"].last_ok_at is None  # продаж и агрегаторов у RS ещё не было
    assert store.has_ok_load("BG", "sales")
    assert not store.has_ok_load("RS", "sales")


def test_страна_без_ошибок_отдаёт_ошибку_none(пиццерии: str) -> None:
    for вид in ("sales", "aggregators", "kr", "ratings"):
        store.finish_load(store.start_load("BG", вид), ok=True)

    (состояние,) = read.load_states()

    assert состояние.last_error is None
    assert состояние.last_ok_at is not None


def test_оценки_периодов_читаются_с_числом_проверок_по_месяцу_начала(пиццерии: str) -> None:
    store.replace_rating_periods(
        date(2026, 9, 1),
        date(2026, 10, 28),
        [А, В],
        [
            RatingPeriod(
                А, "rs", date(2026, 9, 28), date(2026, 10, 4), Decimal("88.5"), "Published"
            ),
            RatingPeriod(А, "rko", date(2026, 10, 5), date(2026, 10, 11), Decimal("91"), None),
            RatingPeriod(В, "rs", date(2026, 10, 5), date(2026, 10, 11), Decimal("70"), None),
        ],
    )
    store.replace_checkup_periods(
        date(2026, 9, 1),
        date(2026, 10, 28),
        [А],
        [
            CheckupPeriod(
                А, "rs", date(2026, 9, 28), date(2026, 10, 4), 3, {"Completed": 2, "Started": 1}
            )
        ],
    )

    сентябрь = read.unit_rating_periods("BG", СЕНТЯБРЬ)
    октябрь = read.unit_rating_periods("BG", ОКТЯБРЬ)

    assert сентябрь == [
        read.UnitRatingPeriod(
            А, "rs", date(2026, 9, 28), date(2026, 10, 4), Decimal("88.50"), "Published", 3
        )
    ]
    assert [(p.kind, p.checkups) for p in октябрь] == [("rko", None)]  # чужая страна не видна
    assert ОКТЯБРЬ in read.months_with_data("BG")


def test_повторная_загрузка_периодов_заменяет_диапазон_у_ответивших(пиццерии: str) -> None:
    период = date(2026, 10, 5)
    store.replace_rating_periods(
        date(2026, 10, 1),
        date(2026, 10, 28),
        [А],
        [RatingPeriod(А, "rs", период, период, Decimal(50), None)],
    )
    store.replace_rating_periods(date(2026, 10, 1), date(2026, 10, 28), [А], [])

    assert read.unit_rating_periods("BG", ОКТЯБРЬ) == []
