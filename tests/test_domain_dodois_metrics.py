"""Разбор и свёртка данных Dodo IS для «Качества» (D671): суммы по пиццерии и месяцу, агрегаторы.

Ответы — по форме из документации (оценки) и по описанию параметров (продажи); настоящих данных
нет. Ядро здесь — суммы: ошибка в них даёт правдоподобное, но неверное число на странице.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from itertools import pairwise

import pytest

from src.domain import dodois_metrics as m

А = "000d3a240c719a8711e68aba13f7f862"
Б = "000d3a240c719a8711e68aba13f7fc8a"
А_С_ДЕФИСАМИ = "000d3a24-0c71-9a87-11e6-8aba13f7f862"


def _строка(unit: str, source: str, channel: str, count: int, amount: float) -> dict:
    return {
        "unitId": unit,
        "orderSource": source,
        "salesChannel": channel,
        "ordersCount": count,
        "sales": amount,
    }


def test_продажи_разбираются_из_плоского_списка() -> None:
    тело = {"result": [_строка(А, "Website", "Delivery", 10, 100.5)]}

    строки = m.sales_rows(тело)

    assert строки == [m.SalesRow(А, "Website", "Delivery", 10, Decimal("100.5"), None)]


def test_продажи_находят_строки_во_вложенном_списке_пиццерии() -> None:
    тело = {
        "result": [
            {
                "unitId": А_С_ДЕФИСАМИ,
                "salesBreakdown": [
                    {"orderSource": "Kiosk", "salesChannel": "Dine-in", "count": 3, "revenue": 30},
                    {
                        "orderSource": "Manager",
                        "salesChannel": "Takeaway",
                        "count": 1,
                        "revenue": 9,
                    },
                ],
            }
        ]
    }

    строки = m.sales_rows(тело)

    assert [(r.dodo_id, r.order_source, r.orders) for r in строки] == [
        (А, "Kiosk", 3),
        (А, "Manager", 1),
    ]


def test_окна_месяца_складываются_в_одну_строку_на_источник_и_канал() -> None:
    окно1 = m.sales_rows([_строка(А, "Website", "Delivery", 10, 100)])
    окно2 = m.sales_rows(
        [_строка(А, "Website", "Delivery", 5, 50.25), _строка(Б, "Kiosk", "Dine-in", 2, 8)]
    )

    итог = m.merge_sales(окно1 + окно2)

    assert итог == [
        m.SalesRow(А, "Website", "Delivery", 15, Decimal("150.25"), None),
        m.SalesRow(Б, "Kiosk", "Dine-in", 2, Decimal("8"), None),
    ]


def test_непонятные_продажи_падают_с_именами_ключей_а_не_значениями() -> None:
    тело = {"result": [{"unitId": А, "total": 999, "секрет": "не-светить"}]}

    with pytest.raises(m.ShapeError) as err:
        m.sales_rows(тело)

    assert "total" in str(err.value)
    assert "999" not in str(err.value)
    assert "не-светить" not in str(err.value)


def test_пустой_ответ_продаж_это_ноль_строк_а_не_сбой() -> None:
    assert m.sales_rows({"result": []}) == []


def test_агрегаторы_считают_заказы_и_выручку_по_пиццерии_и_агрегатору() -> None:
    страница = {
        "sales": [
            {"unitId": А, "aggregatorName": "Glovo", "price": 10},
            {"unitId": А, "aggregatorName": "Glovo", "price": 5.5},
            {"unitId": А, "aggregatorName": "Wolt", "price": 7},
            {"unitId": Б, "aggregatorName": "Glovo", "price": 1},
        ],
        "isEndOfListReached": True,
    }

    итог = m.sum_aggregators(m.aggregator_orders(страница))

    assert итог == [
        m.AggregatorMonth(А, "Glovo", 2, Decimal("15.5")),
        m.AggregatorMonth(А, "Wolt", 1, Decimal("7")),
        m.AggregatorMonth(Б, "Glovo", 1, Decimal("1")),
    ]


def test_строки_без_агрегатора_не_попадают_в_заказы_агрегаторов() -> None:
    страница = {
        "sales": [
            {"unitId": А, "aggregatorName": "Undefined", "price": 10},
            {"unitId": А, "aggregatorName": None, "price": 10},
            {"unitId": А, "price": 10},
            {"unitId": А, "aggregatorName": "JustEat", "price": 4},
        ]
    }

    assert m.sum_aggregators(m.aggregator_orders(страница)) == [
        m.AggregatorMonth(А, "JustEat", 1, Decimal("4"))
    ]


def test_оценки_клиентов_по_документации() -> None:
    тело = {
        "customerRatings": [
            {
                "unitId": А,
                "avgDineInOrderRate": 4.73,
                "avgDeliveryOrderRate": 4.5,
                "dineInRateCount": 210,
                "deliveryRateCount": 40,
            },
            {
                "unitId": Б,
                "avgDineInOrderRate": 0,
                "avgDeliveryOrderRate": 0,
                "dineInRateCount": 0,
                "deliveryRateCount": 0,
            },
        ]
    }

    первая, вторая = m.kr_rows(тело)

    assert (первая.dine_in_avg, первая.dine_in_count) == (Decimal("4.73"), 210)
    assert (первая.delivery_avg, первая.delivery_count) == (Decimal("4.5"), 40)
    assert (вторая.dine_in_avg, вторая.delivery_avg) == (None, None)  # нет оценок — нет среднего


def test_оценки_без_списка_это_сбой_формы() -> None:
    with pytest.raises(m.ShapeError):
        m.kr_rows({"ratings": []})


def test_первая_загрузка_берёт_двенадцать_полных_месяцев_и_текущий() -> None:
    месяцы = m.months_to_load(date(2026, 10, 28), backfill=True)

    assert len(месяцы) == 13
    assert месяцы[0] == date(2026, 10, 1)
    assert месяцы[-1] == date(2025, 10, 1)


def test_обычный_заход_берёт_текущий_и_прошлый_через_границу_года() -> None:
    assert m.months_to_load(date(2027, 1, 15), backfill=False) == [
        date(2027, 1, 1),
        date(2026, 12, 1),
    ]


def test_конец_текущего_месяца_не_позже_вчера() -> None:
    assert m.month_end(date(2026, 10, 1), date(2026, 10, 28)) == date(2026, 10, 27)
    assert m.month_end(date(2026, 9, 1), date(2026, 10, 28)) == date(2026, 9, 30)


def test_окна_покрывают_месяц_без_дыр_и_пересечений() -> None:
    окна = m.windows(date(2026, 9, 1), date(2026, 9, 30), 7)

    assert окна[0] == (date(2026, 9, 1), date(2026, 9, 7))
    assert окна[-1] == (date(2026, 9, 29), date(2026, 9, 30))
    for (_, конец), (начало, _) in pairwise(окна):
        assert (начало - конец).days == 1


def test_окна_пусты_если_конец_раньше_начала() -> None:
    assert m.windows(date(2026, 10, 1), date(2026, 9, 30), 7) == []


def test_оценки_периодов_разбираются_по_ответу_с_prod() -> None:
    тело = {
        "unitRates": [
            {
                "unitId": А_С_ДЕФИСАМИ,
                "periodFrom": "2026-10-05",
                "periodTo": "2026-10-11T23:59:59",
                "rate": 91.25,
                "publishStatus": "Published",
            }
        ],
        "isEndOfListReached": True,
    }

    (строка,) = m.rating_periods(тело, m.RATING_RKO)

    assert строка == m.RatingPeriod(
        А, "rko", date(2026, 10, 5), date(2026, 10, 11), Decimal("91.25"), "Published"
    )


def test_оценка_периода_без_даты_это_сбой_формы() -> None:
    with pytest.raises(m.ShapeError):
        m.rating_periods({"unitRates": [{"unitId": А, "rate": 90}]}, m.RATING_RS)


def _проверка(номер: str, unit: str, вид: str, статус: str) -> dict:
    return {
        "id": номер,
        "unitId": unit,
        "periodFrom": "2026-10-05",
        "periodTo": "2026-10-11",
        "ratingKind": вид,
        "status": статус,
    }


def test_проверки_считаются_по_пиццерии_виду_и_периоду_с_разбивкой_по_статусу() -> None:
    тело = {
        "checkups": [
            _проверка("1", А, "Standards", "Completed"),
            _проверка("2", А, "Standards", "Completed"),
            _проверка("3", А, "Standards", "InProgress"),
            _проверка("4", А, "CustomerExperience", "Completed"),
            _проверка("5", Б, "Standards", "Completed"),
        ]
    }

    итог = {(c.dodo_id, c.kind): c for c in m.checkup_periods(тело)}

    assert итог[(А, "rs")].checkups == 3
    assert итог[(А, "rs")].by_status == {"Completed": 2, "InProgress": 1}
    assert итог[(А, "rko")].checkups == 1
    assert итог[(Б, "rs")].checkups == 1


def test_проверка_из_двух_окон_запроса_считается_один_раз() -> None:
    одна = _проверка("7", А, "Standards", "Completed")

    (итог,) = m.checkup_periods([одна, dict(одна)])

    assert итог.checkups == 1


def test_в_счёт_проверок_не_попадают_номера_и_люди() -> None:
    (итог,) = m.checkup_periods([_проверка("secret-id-42", А, "Standards", "Completed")])

    assert "secret-id-42" not in repr(итог)
