"""Привязка пиццерии к Migros Yemek по ссылке (#717)."""

from __future__ import annotations

from datetime import date

import pytest

from src.ratings.aggregators import migros, migros_link
from src.ratings.aggregators.base import AggregatorError
from src.ratings.maps_link import DodoUnit

СЕГОДНЯ = date(2026, 10, 12)
SLUG = "dodo-pizza-cukurova-st-2e024"
URL = f"https://www.migros.com.tr/yemek/{SLUG}"
RELAY = "http://100.64.1.2:9021"


def _unit(country: str = "TR") -> DodoUnit:
    return DodoUnit("a" * 32, "Adana-9", 37.0, 35.3, country)


class _Http:
    def __init__(self, answer: object) -> None:
        self.answer = answer
        self.urls: list[str] = []

    def get(self, url: str, headers: object = None) -> object:
        self.urls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _карточка(title: str = "Dodo Pizza, Çukurova") -> dict[str, object]:
    return {
        "storeDTO": {
            "id": 42,
            "cityId": 1,
            "title": title,
            "rating": {"score": "4,6", "commentCount": 120},
        }
    }


@pytest.fixture(autouse=True)
def _ретранслятор(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(migros.RELAY_VAR, RELAY)


@pytest.mark.parametrize(
    "url",
    [URL, f"https://migros.com.tr/yemek/{SLUG}/", f"{URL}?utm=x#top", f"  {URL}  "],
)
def test_ссылка_даёт_slug(url: str) -> None:
    assert migros_link.parse_store_url(url) == SLUG


@pytest.mark.parametrize(
    "url",
    [
        f"http://www.migros.com.tr/yemek/{SLUG}",
        f"https://www.migros.com.tr.evil.example/yemek/{SLUG}",
        f"https://evil.example/yemek/{SLUG}",
        f"https://www.migros.com.tr:8443/yemek/{SLUG}",
        f"https://user@www.migros.com.tr/yemek/{SLUG}",
        f"https://www.migros.com.tr/yemek/{SLUG}/menu",
        "https://www.migros.com.tr/yemek/../admin",
        "https://www.migros.com.tr/yemek/Dodo",
        "не ссылка",
    ],
)
def test_чужой_хост_и_кривой_путь_отвергаются(url: str) -> None:
    assert migros_link.parse_store_url(url) is None


def test_додо_по_ссылке_привязывается_с_оценкой() -> None:
    http = _Http(_карточка())

    итог, точка, оценка = migros_link.link_by_url(_unit(), URL, set(), СЕГОДНЯ, http=http)  # type: ignore[arg-type]

    assert итог.code == migros_link.OK and итог.point_key == SLUG
    assert http.urls == [f"{RELAY}/stores/{SLUG}"]
    assert точка is not None and (точка.aggregator, точка.dodo_id) == (migros.KEY, "a" * 32)
    assert (точка.country_code, точка.dodo_name, точка.url) == ("TR", "Adana-9", URL)
    assert оценка is not None and (оценка.score, оценка.scale, оценка.votes) == (4.6, 5, 120)


@pytest.mark.parametrize(
    ("unit", "url", "taken", "answer", "code"),
    [
        (None, URL, set(), _карточка(), migros_link.UNKNOWN_UNIT),
        (_unit(), "https://glovoapp.com/x", set(), _карточка(), migros_link.BAD_URL),
        (_unit("RO"), URL, set(), _карточка(), migros_link.COUNTRY_MISMATCH),
        (_unit(), URL, {SLUG}, _карточка(), migros_link.TAKEN),
        (_unit(), URL, set(), _карточка("Dodo Burger"), migros_link.NO_STORE),
        (_unit(), URL, set(), {"storeDTO": None}, migros_link.NO_STORE),
        (_unit(), URL, set(), AggregatorError("HTTP 403"), migros_link.MIGROS_FAILED),
    ],
)
def test_отказы_привязки(
    unit: DodoUnit | None, url: str, taken: set[str], answer: object, code: str
) -> None:
    итог, точка, оценка = migros_link.link_by_url(unit, url, taken, СЕГОДНЯ, http=_Http(answer))  # type: ignore[arg-type]

    assert итог.code == code and точка is None and оценка is None
