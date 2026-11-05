"""Валюта выручки Dodo IS по стране (D713): справочник закрыт, чужая страна — `None`."""

from __future__ import annotations

import pytest

from src.domain.country_currency import COUNTRY_CURRENCY, currency_of


@pytest.mark.parametrize(
    ("country", "currency"),
    [("RS", "RSD"), ("SI", "EUR"), ("hr", "EUR"), ("BG", "EUR"), ("ME", "EUR"), ("PL", "PLN")],
)
def test_валюта_страны(country: str, currency: str) -> None:
    assert currency_of(country) == currency


@pytest.mark.parametrize("country", ["ZZ", "", "RU", "XX"])
def test_страна_вне_перечня_без_валюты(country: str) -> None:
    assert currency_of(country) is None


def test_перечень_только_коды_стран_и_валют() -> None:
    assert all(len(cc) == 2 and cc.isupper() for cc in COUNTRY_CURRENCY)
    assert all(len(cur) == 3 and cur.isupper() for cur in COUNTRY_CURRENCY.values())
