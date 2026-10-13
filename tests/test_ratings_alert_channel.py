"""Канал уведомлений о сбое сбора: `http://` только для внутренних имён."""

from __future__ import annotations

import pytest

from src.ratings.aggregators.alert import SECRET_VAR, URL_VAR, channel


def _env(url: str) -> dict[str, str]:
    return {URL_VAR: url, SECRET_VAR: "k"}


@pytest.mark.parametrize(
    "url",
    [
        "https://notify.example.org",
        "https://notify.example.org/",
        "http://localhost:8080",
        "http://furca-notify:8080",
        "http://furca-notify",
        "http://127.0.0.1:8080",
        "http://10.0.0.5:8090",
    ],
)
def test_allowed_urls_give_channel(url: str) -> None:
    target = channel(_env(url))
    assert target is not None
    assert target[0].endswith("/notify")


@pytest.mark.parametrize(
    "url",
    ["http://notify.example.org", "http://8.8.8.8:8080", "http://notify.example.org:80/x"],
)
def test_plain_http_to_external_host_is_off(url: str) -> None:
    assert channel(_env(url)) is None


def test_missing_secret_or_url_is_off() -> None:
    assert channel({URL_VAR: "https://notify.example.org"}) is None
    assert channel({SECRET_VAR: "k"}) is None
