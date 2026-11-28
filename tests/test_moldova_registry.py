"""Moldova is a shared network country, not an iSpring-only exception."""

from src.domain.geo import COUNTRIES
from src.ratings.countries import country_code


def test_moldova_is_in_the_shared_registry():
    assert COUNTRIES["MD"] == {"ru": "Молдова", "en": "Moldova"}
    assert country_code("Moldova") == country_code("Молдова") == "MD"
