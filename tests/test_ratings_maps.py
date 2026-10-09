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
