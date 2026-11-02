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


def test_оценки_периодов_читаются_с_числом_проверок(пиццерии: str) -> None:
    store.replace_rating_periods(
        date(2026, 9, 1),
        date(2026, 10, 28),
        [А, В],
        [
            RatingPeriod(
                А, "rs", date(2026, 9, 14), date(2026, 10, 4), Decimal("88.5"), "Published"
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
                А, "rs", date(2026, 9, 14), date(2026, 10, 4), 3, {"Completed": 2, "Started": 1}
            )
        ],
    )

    сентябрь = read.unit_rating_periods("BG", СЕНТЯБРЬ)
    октябрь = read.unit_rating_periods("BG", ОКТЯБРЬ)

    assert сентябрь == [
        read.UnitRatingPeriod(
            А, "rs", date(2026, 9, 14), date(2026, 10, 4), Decimal("88.50"), "Published", 3
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


def test_рс_уходит_в_месяц_большинства_дней_а_рко_в_месяц_начала(пиццерии: str) -> None:
    # Живые периоды Dodo IS (28.10.2026): РС не по календарным половинам.
    store.replace_rating_periods(
        date(2026, 8, 1),
        date(2026, 10, 28),
        [А],
        [
            RatingPeriod(А, "rko", date(2026, 8, 31), date(2026, 9, 6), Decimal("83.5"), None),
            RatingPeriod(А, "rko", date(2026, 9, 28), date(2026, 10, 4), Decimal("84.33"), None),
            RatingPeriod(А, "rs", date(2026, 8, 31), date(2026, 9, 13), Decimal(92), None),
            RatingPeriod(А, "rs", date(2026, 9, 14), date(2026, 10, 4), Decimal(88), None),
            RatingPeriod(А, "rs", date(2026, 10, 5), date(2026, 10, 18), Decimal(70), None),
        ],
    )

    сентябрь = [(p.kind, p.period_from, p.rate) for p in read.unit_rating_periods("BG", СЕНТЯБРЬ)]
    август = [(p.kind, p.period_from) for p in read.unit_rating_periods("BG", date(2026, 8, 1))]

    assert сентябрь == [
        ("rko", date(2026, 9, 28), Decimal("84.33")),
        ("rs", date(2026, 8, 31), Decimal("92.00")),
        ("rs", date(2026, 9, 14), Decimal("88.00")),
    ]
    assert август == [("rko", date(2026, 8, 31))]


def test_retry_boundary_periods_before_requested_range_is_idempotent(пиццерии: str) -> None:
    start, stop = date(2026, 10, 1), date(2026, 11, 2)
    boundary = date(2026, 9, 14)
    for score in (Decimal(80), Decimal(90)):
        store.replace_rating_periods(
            start, stop, [А], [RatingPeriod(А, "rs", boundary, date(2026, 10, 4), score, None)]
        )
        store.replace_checkup_periods(
            start,
            stop,
            [А],
            [CheckupPeriod(А, "rs", boundary, date(2026, 10, 4), 2, {"Completed": 2})],
        )
    rows = read.unit_rating_periods("BG", СЕНТЯБРЬ)
    assert len(rows) == 1
    assert rows[0].rate == Decimal(90)
    assert rows[0].checkups == 2


def test_partial_access_does_not_write_rows_of_uncovered_units(пиццерии: str) -> None:
    start, stop = date(2026, 10, 1), date(2026, 11, 2)
    rows = [
        RatingPeriod(А, "rs", start, date(2026, 10, 14), Decimal(80), None),
        RatingPeriod(Б, "rs", start, date(2026, 10, 14), Decimal(40), None),
    ]
    assert store.replace_rating_periods(start, stop, [А], rows) == 1
    assert {r.dodo_id for r in read.unit_rating_periods("BG", ОКТЯБРЬ)} == {А}


def test_customer_section_reads_only_selected_months_countries_and_kr_health(пиццерии: str) -> None:
    from src.db import customer_ratings

    store.replace_kr(
        СЕНТЯБРЬ, [А, В], [KrRow(А, Decimal(5), 1, None, 0), KrRow(В, Decimal(1), 99, None, 0)]
    )
    store.replace_kr(ОКТЯБРЬ, [А], [KrRow(А, Decimal(1), 9, None, 0)])
    rows = customer_ratings.monthly(("BG",), СЕНТЯБРЬ, ОКТЯБРЬ)
    assert [(r.country, r.unit, r.month, r.dine_count) for r in rows] == [
        ("BG", А, СЕНТЯБРЬ, 1),
        ("BG", А, ОКТЯБРЬ, 9),
    ]
    assert customer_ratings.latest_month(("BG",)) == ОКТЯБРЬ
    assert read.latest_available_month(("RS",)) == СЕНТЯБРЬ
    store.finish_load(store.start_load("BG", "kr"), ok=True, rows=1)
    store.finish_load(store.start_load("BG", "ratings"), ok=False, error="synthetic")
    assert not customer_ratings.loads(("BG",))[0].failed
    store.finish_load(store.start_load("BG", "kr"), ok=False, error="synthetic")
    assert customer_ratings.loads(("BG",))[0].failed
    assert customer_ratings.loads(("BG",))[0].last_ok is not None


def test_latest_month_uses_rating_month_for_cross_month_rs(пиццерии: str) -> None:
    store.replace_rating_periods(
        date(2026, 8, 1),
        date(2026, 9, 30),
        [А],
        [RatingPeriod(А, "rs", date(2026, 8, 31), date(2026, 9, 13), Decimal(80), None)],
    )
    assert read.latest_available_month(("BG",)) == СЕНТЯБРЬ
    assert read.months_with_data("BG") == [СЕНТЯБРЬ]


def test_official_registry_fallback_keeps_primary_identity_and_country_scope(пиццерии: str) -> None:
    from src.db import customer_ratings

    new = "d" * 32
    with psycopg.connect(пиццерии) as conn:
        # A contradictory public row must not move the primary BG identity into RS.
        for ident, code, name in (
            (А, "RS", "Public conflicting name"),
            (new, "RS", "Official new unit"),
        ):
            conn.execute(
                "insert into agg.units(dodo_id,country_code,name,lat,lng,working,last_seen) "
                "values(%s,%s,%s,0,0,true,current_date)",
                (ident, code, name),
            )
    store.replace_kr(
        СЕНТЯБРЬ, [А, new], [KrRow(А, Decimal(4), 2, None, 0), KrRow(new, Decimal(5), 3, None, 0)]
    )
    store.replace_sales(
        СЕНТЯБРЬ, [new], [SalesRow(new, "MobileApp", "Delivery", 1, Decimal(10), None)]
    )
    store.replace_aggregators(СЕНТЯБРЬ, [new], [AggregatorMonth(new, "Wolt", 1, None)])
    store.replace_rating_periods(
        СЕНТЯБРЬ,
        date(2026, 9, 30),
        [new],
        [RatingPeriod(new, "rs", СЕНТЯБРЬ, date(2026, 9, 14), Decimal(90), None)],
    )
    assert [r.dodo_id for r in read.unit_kr("RS", СЕНТЯБРЬ)] == [new]
    assert [r.dodo_id for r in read.unit_kr("BG", СЕНТЯБРЬ)] == [А]
    assert [r.dodo_id for r in read.unit_sales("RS", СЕНТЯБРЬ)] == [new]
    assert [r.dodo_id for r in read.unit_aggregator_orders("RS", СЕНТЯБРЬ)] == [new]
    assert [r.dodo_id for r in read.unit_rating_periods("RS", СЕНТЯБРЬ)] == [new]
    assert read.latest_available_month(("RS",)) == СЕНТЯБРЬ
    assert customer_ratings.latest_month(("RS",)) == СЕНТЯБРЬ
    rows = customer_ratings.monthly(("RS",), СЕНТЯБРЬ, ОКТЯБРЬ)
    assert [(r.unit, r.name, r.country) for r in rows] == [(new, "Official new unit", "RS")]
    all_rows = customer_ratings.monthly(("BG", "RS"), СЕНТЯБРЬ, ОКТЯБРЬ)
    assert len(all_rows) == 2
    assert next(r.name for r in all_rows if r.unit == А) == А[:3]
    assert customer_ratings.monthly(("HR",), СЕНТЯБРЬ, ОКТЯБРЬ) == []
