"""Query-country links retain the ordinary default for invalid or foreign countries."""

import pytest
from flask import Flask

from src.db.reach import Reach
from src.web import country_page


@pytest.mark.parametrize(
    "query,scope,expected",
    [
        ("rs", None, "/country/RS"),
        ("RS", ("AM",), None),
        ("garbage", None, None),
        ("ZZ", None, None),
    ],
)
def test_query_country_is_valid_and_available(monkeypatch, query, scope, expected):
    app = Flask(__name__)
    app.add_url_rule("/country/<code>", endpoint="country", view_func=lambda code: code)
    monkeypatch.setattr(country_page.auth, "current_reach", lambda: Reach("HQ", None, scope))
    monkeypatch.setattr(country_page.country_data, "countries", lambda **_: (("AM", 4), ("RS", 2)))
    with app.test_request_context("/country?country=" + query):
        response = country_page.country_param_redirect()
    assert (response.location if response is not None else None) == expected
