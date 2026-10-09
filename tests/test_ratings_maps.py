"""Оценки на картах: средняя страны по всем отзывам и разбор ответа Pointer.

Ядро (D369): цифра, которую читают как факт, и внешние данные на границе.
"""

from __future__ import annotations

from datetime import date

from src.db.maps_store import LatestRating
from src.ratings import pointer
from src.ratings.maps import summarize

ДЕНЬ = date(2026, 10, 9)


def test_средняя_страны_взвешена_отзывами_и_без_пустых_филиалов() -> None:
    # Arrange — 4.8 по 10 отзывам не перевешивает 4.0 по 990; филиал без отзывов
    # в среднее не входит, но в счёт филиалов входит.
    строки = [
        LatestRating("RS", pointer.GOOGLE, 4.8, 10, ДЕНЬ),
        LatestRating("RS", pointer.GOOGLE, 4.0, 990, ДЕНЬ),
        LatestRating("RS", pointer.GOOGLE, 0.0, 0, ДЕНЬ),
        LatestRating("BY", pointer.GOOGLE, 3.0, 5, ДЕНЬ),
    ]

    # Act
    (сербия, хорватия) = summarize(строки, ("RS", "HR"))

    # Assert
    google = сербия.scores[pointer.GOOGLE]
    assert google.avg == 4.01 and google.reviews == 1000 and google.branches == 3
    assert сербия.scores[pointer.YANDEX].avg is None
    assert хорватия.as_of is None and хорватия.scores[pointer.GOOGLE].branches == 0


def test_кривой_филиал_и_кривая_оценка_отбрасываются() -> None:
    assert pointer.parse_company({"name": "Додо"}, {}) is None  # без uuid
    филиал = pointer.parse_company(
        {
            "uuid": "u1",
            "name": "Додо",
            "country_code": "rs",
            "ratings": [
                {"provider_id": 2, "date": "2026-10-09", "avg_rating": 4.5, "ratings_count": 7},
                {"provider_id": 1, "date": "вчера", "avg_rating": 4.0, "ratings_count": 1},
                {"provider_id": 1, "date": "2026-10-09", "avg_rating": 7, "ratings_count": 1},
            ],
        },
        {},
    )
    assert филиал is not None and филиал.country_code == "RS"
    assert [(r.provider_id, r.avg_rating) for r in филиал.ratings] == [(2, 4.5)]


def test_изменение_страны_к_прошлому_периоду() -> None:
    from src.ratings.maps import with_delta

    сейчас = summarize([LatestRating("RS", pointer.GOOGLE, 4.5, 100, ДЕНЬ)], ("RS",))
    было = summarize([LatestRating("RS", pointer.GOOGLE, 4.4, 80, ДЕНЬ)], ("RS",))
    пусто = summarize([], ("RS",))

    assert with_delta(сейчас, было)[0].scores[pointer.GOOGLE].delta == 0.1
    assert with_delta(сейчас, пусто)[0].scores[pointer.GOOGLE].delta is None
    assert with_delta(сейчас, было)[0].scores[pointer.YANDEX].delta is None


def test_история_филиала_разбирается_по_дням() -> None:
    ответ = {
        "items": [
            {
                "date": "2026-09-09",
                "ratings": [{"provider_id": 2, "avg_rating": 4.6, "ratings_count": 1051}],
            },
            {
                "date": "кривая",
                "ratings": [{"provider_id": 2, "avg_rating": 4.6, "ratings_count": 1}],
            },
        ]
    }
    оценки = pointer.history(lambda _путь: ответ, "u1", ДЕНЬ, ДЕНЬ)
    assert [(r.on_date, r.avg_rating, r.ratings_count) for r in оценки] == [
        (date(2026, 9, 9), 4.6, 1051)
    ]


def test_филиал_связывается_с_ближайшей_пиццерией_в_пороге() -> None:
    from src.ratings.maps_link import DodoUnit, Point, match

    # Arrange — Ozo 18 в Вильнюсе: филиал в ~30 м от пиццерии; второй филиал —
    # дубль той же точки дальше; третий — в 1,2 км от Vilnius-5 при однозначном
    # отрыве; четвёртый — в 2 км от Vilnius-5, дальше предела.
    озас = DodoUnit("a" * 32, "Vilnius-4", 54.7140677, 25.272872)
    лайсвес = DodoUnit("b" * 32, "Vilnius-5", 54.6945595, 25.2171669)
    точки = [
        Point("p1", 54.71430, 25.27260),
        Point("p2", 54.71450, 25.27200),
        Point("p3", 54.70, 25.20),  # ~1,2 км от Vilnius-5, Vilnius-4 вчетверо дальше
        Point("p4", 54.6765, 25.1885),  # ~2,8 км от Vilnius-5 — дальше предела
    ]

    # Act
    связи = match(точки, [озас, лайсвес])

    # Assert
    assert sorted((x.company_uuid, x.dodo_name) for x in связи) == [
        ("p1", "Vilnius-4"),
        ("p3", "Vilnius-5"),
    ]
    assert связи[0].distance_m < 50


def test_пиццерия_из_публичного_api_без_координат_и_офис_отбрасываются() -> None:
    from src.ratings.maps_link import parse_units

    ответ = [
        {
            "Type": 0,
            "UUId": "c" * 32,
            "Name": "Office",
            "Location": {"Latitude": 1, "Longitude": 1},
        },
        {
            "Type": 1,
            "UUId": "D" * 32,
            "Name": "Vilnius-1",
            "Location": {"Latitude": 54.7, "Longitude": 25.3},
        },
        {
            "Type": 1,
            "UUId": "e" * 32,
            "Name": "Без точки",
            "Location": {"Latitude": 0, "Longitude": 0},
        },
        {"Type": 1, "UUId": "короткий", "Name": "x", "Location": {"Latitude": 1, "Longitude": 1}},
    ]
    assert [(u.dodo_id, u.name) for u in parse_units(ответ)] == [("d" * 32, "Vilnius-1")]


def test_спорная_дальняя_пиццерия_не_связывается() -> None:
    """В 800 м от филиала две пиццерии почти на равном расстоянии — не угадываем."""
    from src.ratings.maps_link import DodoUnit, Point, match

    левая = DodoUnit("a" * 32, "Город-1", 54.700, 25.000)
    правая = DodoUnit("b" * 32, "Город-2", 54.700, 25.024)
    assert match([Point("p", 54.7065, 25.012)], [левая, правая]) == ()
