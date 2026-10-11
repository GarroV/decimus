"""Оценки в агрегаторах доставки (#638, D389): разбор ответов витрин, привязка
точек к пиццериям, страж пустого ответа и сводка по группам.

Ядро (D369): цифра, которую читают как факт, и внешние данные на границе.
Образцы ответов — урезанные настоящие ответы витрин от 11.10.2026.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.db.agg_store import LatestRating, PointRow
from src.ratings.aggregators import (
    bolt,
    chowdeck,
    collect,
    glovo,
    pyszne,
    summary,
    trendyol,
    wolt,
    yandex_eda,
    yemeksepeti,
)
from src.ratings.aggregators.base import AggregatorError, is_dodo, votes_of

ДЕНЬ = date(2026, 10, 11)


def test_додо_узнаётся_по_названию_сети_а_двойники_нет() -> None:
    assert is_dodo("Dodo Pizza | Burgas") and is_dodo("Додо пицца") and is_dodo("DODO PIZZA (Tuna)")
    assert not is_dodo("Dodo Doner N1") and not is_dodo("Dodonut") and not is_dodo("Dodos Tost")
    assert not is_dodo(None)


def test_число_оценок_и_ступень() -> None:
    assert votes_of(1467) == (1467, True)
    assert votes_of("500+") == (500, False)
    assert votes_of("(1500+)") == (1500, False)
    assert votes_of("870") == (870, True)
    assert votes_of(None) == (None, True)
    assert votes_of(True) == (None, True)


def test_wolt_берёт_додо_с_координатами_из_пары_lon_lat() -> None:
    ответ = {
        "sections": [
            {
                "items": [
                    {
                        "venue": {
                            "name": "Dodo Pizza Kesklinn",
                            "slug": "dodo-pizza-kesklinn",
                            "location": [24.76133, 59.4348762],
                            "rating": {"score": 8.6, "volume": 715},
                            "online": False,
                        }
                    },
                    {"venue": {"name": "Dodo Doner N1", "slug": "dodo-doner"}},
                    {"venue": {"name": "Dodo Pizza", "slug": None}},
                    {"title": "без заведения"},
                ]
            }
        ]
    }

    (точка,) = wolt.parse(ответ, "EE")

    assert точка.point_key == "dodo-pizza-kesklinn" and точка.scale == 10
    assert (точка.lat, точка.lng) == (59.4348762, 24.76133)
    assert (точка.score, точка.votes, точка.votes_exact, точка.is_open) == (8.6, 715, True, False)
    assert точка.url == "https://wolt.com/en/est/x/restaurant/dodo-pizza-kesklinn"


def test_bolt_город_без_bolt_пуст_а_чужая_ошибка_сбой() -> None:
    assert bolt.parse({"code": 5812, "message": "CITY_NOT_FOUND"}) == []
    with pytest.raises(AggregatorError):
        bolt.parse({"code": 1005, "message": "TOO_MANY_REQUESTS"})
    ответ = {
        "code": 0,
        "data": {
            "providers": [
                {
                    "provider_id": 57831,
                    "name": {"value": "Dodo Pizza Kesklinn"},
                    "lat": 59.43499,
                    "lng": 24.76092,
                    "rating_info": {"rating": 4.42, "count": 1467},
                    "slug": "57831-dodo-pizza-kesklinn",
                    "is_available_for_delivery": True,
                },
                {"provider_id": 1, "name": {"value": "Lido"}},
            ]
        },
    }

    (точка,) = bolt.parse(ответ)

    assert (точка.point_key, точка.score, точка.scale, точка.votes) == ("57831", 4.42, 5, 1467)
    assert точка.url == "https://food.bolt.eu/en/provider/57831-dodo-pizza-kesklinn"


def test_яндекс_еда_находит_точку_в_глубине_выдачи_и_читает_карточку() -> None:
    выдача = {
        "blocks": [
            {
                "payload": [
                    {"slug": "papi", "title": "Папи", "brand": {"slug": "papi_by"}},
                    {
                        "slug": "dodo_kwls7",
                        "title": "Додо Пицца",
                        "brand": {"slug": "dodo_picca"},
                        "available": False,
                    },
                ]
            }
        ]
    }
    assert yandex_eda.places(выдача) == {"dodo_kwls7": False}
    карточка = {
        "payload": {
            "foundPlace": {
                "place": {
                    "name": "Додо Пицца",
                    "rating": 4.6,
                    "ratingCount": "870",
                    "brand": {"slug": "dodo_picca"},
                    "address": {
                        "location": {"latitude": 53.902777, "longitude": 27.547575},
                        "short": "Минск, Романовская Слобода, 8",
                    },
                }
            }
        }
    }

    точка = yandex_eda.card(карточка, "dodo_kwls7", False)

    assert точка is not None and (точка.score, точка.votes, точка.scale) == (4.6, 870, 5)
    assert (точка.lat, точка.lng) == (53.902777, 27.547575)
    assert yandex_eda.card({"payload": {}}, "x", None) is None


def test_yemeksepeti_trendyol_pyszne() -> None:
    (ys,) = yemeksepeti.parse(
        {
            "data": {
                "items": [
                    {
                        "code": "e8c9",
                        "name": "Dodo Pizza",
                        "rating": 4.5,
                        "review_number": 1673,
                        "latitude": 38.4582925,
                        "longitude": 27.117417,
                        "is_active": True,
                    },
                    {"code": "zz", "name": "Dodo Burger"},
                ]
            }
        }
    )
    assert (ys.point_key, ys.score, ys.votes) == ("e8c9", 4.5, 1673)

    assert trendyol.suggested_ids(
        {"suggestions": [{"items": [{"restaurantId": 221570}, {"restaurantId": 221570}]}]}
    ) == [221570]
    tgo = trendyol.card(
        {
            "restaurant": {
                "info": {
                    "id": 221570,
                    "name": "Dodo Pizza (Tuna)",
                    "score": {"overall": 4.7, "ratingText": "(1500+)"},
                    "location": {"point": "38.4583,27.1175"},
                    "status": "CLOSED",
                }
            }
        }
    )
    assert tgo is not None and (tgo.score, tgo.votes, tgo.votes_exact) == (4.7, 1500, False)
    assert (tgo.lat, tgo.lng, tgo.is_open) == (38.4583, 27.1175, False)

    (py,) = pyszne.parse(
        {
            "restaurants": [
                {
                    "name": "Dodo Pizza Rondo ONZ",
                    "uniqueName": "dodo-pizza-rondo-onz",
                    "rating": {"count": 246, "starRating": 4.3},
                    "address": {"location": {"coordinates": [20.99854, 52.233974]}},
                    "availability": {"delivery": {"isOpen": True}},
                }
            ]
        }
    )
    assert (py.score, py.votes, py.lat, py.lng) == (4.3, 246, 52.233974, 20.99854)


def _точка(aggregator: str, key: str) -> PointRow:
    return PointRow(
        aggregator, key, "RO", "Dodo Pizza", None, None, None, "a" * 32, "B-1", None, {}
    )


def test_glovo_доля_в_проценты_и_чужая_точка_это_сбой() -> None:
    точка = _точка("glovo", "306069")
    ответ = {"addressId": 306069, "ratingInfo": {"ratingValue": 0.983, "ratingCount": 591}}

    найдено = glovo.parse(ответ, точка)

    assert (найдено.score, найдено.scale, найдено.votes) == (98.3, 100, 591)
    with pytest.raises(AggregatorError):
        glovo.parse({**ответ, "addressId": 312213}, точка)


def test_chowdeck_оценка_строкой_и_не_додо_это_сбой() -> None:
    точка = _точка("chowdeck", "106110")
    ответ = {
        "data": {
            "name": "Dodo Pizza - Alausa",
            "average_rating": "4.17",
            "number_of_rating": 1065,
            "coordinate": {"x": 3.36, "y": 6.61},
            "is_active": True,
        }
    }
    найдено = chowdeck.parse(ответ, точка)
    assert (найдено.score, найдено.votes, найдено.lat, найдено.lng) == (4.17, 1065, 6.61, 3.36)
    with pytest.raises(AggregatorError):
        chowdeck.parse({"data": {"name": "Pizza Hut"}}, точка)


def test_привязка_ближайшая_и_одна_к_одной() -> None:
    # Точка «a» в 10 м от пиццерии 1 и в 50 м от 2; точка «b» в 30 м от 1 и в
    # 60 м от 2 — пиццерия 1 достаётся «a», «b» идёт к 2. Дальше 400 м — не пара.
    пары = collect.assign(
        [("a", "u1", 10.0), ("a", "u2", 50.0), ("b", "u1", 30.0), ("b", "u2", 60.0),
         ("c", "u3", 401.0)]
    )  # fmt: skip
    assert пары == {"a": ("u1", 10), "b": ("u2", 60)}


def test_страж_пустого_ответа() -> None:
    assert collect.verdict(points=45, errors=0, attempts=45, last_ok_points=45) is None
    assert collect.verdict(points=0, errors=0, attempts=0, last_ok_points=0) is None  # впервые
    пусто = collect.verdict(points=0, errors=0, attempts=45, last_ok_points=45)
    assert пусто is not None and "45" in пусто
    молчит = collect.verdict(points=0, errors=12, attempts=12, last_ok_points=0)
    assert молчит is not None and "12" in молчит
    assert collect.verdict(points=40, errors=3, attempts=45, last_ok_points=45) is None


def test_сводка_взвешена_числом_оценок_в_родной_шкале() -> None:
    строки = [
        LatestRating("RO", "wolt", "a" * 32, 9.2, 10, 1000, ДЕНЬ),
        LatestRating("RO", "wolt", "b" * 32, 8.0, 10, 0, ДЕНЬ),
        LatestRating("RO", "glovo", "a" * 32, 98.3, 100, 591, ДЕНЬ),
        LatestRating("BG", "wolt", "c" * 32, 9.0, 10, None, ДЕНЬ),
    ]

    (ro, cee, hr) = summary.summarize(
        строки, [("RO", ("RO",)), ("CEE", ("RO", "BG")), ("HR", ("HR",))]
    )

    assert ro.scores["wolt"].avg == round((9.2 * 1000 + 8.0 * 1) / 1001, 2)
    assert ro.scores["wolt"].points == 2 and ro.scores["glovo"].avg == 98.3
    assert cee.scores["wolt"].points == 3 and hr.scores == {} and hr.as_of is None
    assert summary.aggregators_of(строки) == ("wolt", "glovo")
