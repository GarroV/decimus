"""Раздел «Рейтинги» человеческим языком: периоды словами, названия стран из одного справочника,
шапка без служебного текста, на «Картах» нет второго отбора по странам."""

from __future__ import annotations

import re
from datetime import date

import pytest
from ratings_page import подготовить, получить

from src.domain.geo import COUNTRIES, COUNTRY_NAMES, EXTRA_COUNTRIES
from src.ratings import countries as rcountries
from src.ratings.periods import month_period, quarter_period
from src.web import ratings_words
from src.web.geo_names import country_title


def test_месяцы_и_кварталы_словами() -> None:
    assert ratings_words.period_title(quarter_period(2026, 3), "ru") == "III квартал 2026"
    assert ratings_words.period_title(quarter_period(2026, 3), "en") == "Q3 2026"
    assert ratings_words.period_title(month_period(2026, 9), "ru") == "сентябрь 2026"
    assert ratings_words.months_phrase((date(2026, 10, 1), date(2026, 11, 1)), "ru") == (
        "октябрь и ноябрь 2026"
    )
    assert ratings_words.months_phrase((date(2025, 12, 1), date(2026, 1, 1)), "ru") == (
        "декабрь 2025 и январь 2026"
    )


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_мексика_называется_словом_а_не_кодом(lang: str) -> None:
    assert country_title("MX", lang) == {"ru": "Мексика", "en": "Mexico"}[lang]


def test_справочник_названий_стран_один() -> None:
    assert rcountries.NAMES is COUNTRY_NAMES
    assert set(COUNTRY_NAMES) == set(COUNTRIES) | set(EXTRA_COUNTRIES)
    # ни одна страна справочника не показывается кодом
    for code in COUNTRY_NAMES:
        assert country_title(code, "ru") != code and country_title(code, "en") != code


def test_шапка_раздела_заголовок_и_вопросик_без_служебной_строки(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    подготовить(monkeypatch)
    for раздел, заголовок in (("maps", "Карты"), ("clients", "Оценки клиентов")):
        html = получить(monkeypatch, f"/ratings/{раздел}")
        шапка = re.search(r'<header class="page-heading">(.*?)</header>', html, flags=re.S)
        assert шапка
        assert f'<h1 class="rt-head__title">{заголовок}</h1>' in шапка.group(1)
        assert "rt-fresh-line" not in html and "rt-head__kicker" not in html


def test_карты_без_второго_отбора_по_странам(monkeypatch: pytest.MonkeyPatch) -> None:
    подготовить(monkeypatch)
    html = получить(monkeypatch, "/ratings/maps")

    assert "rt-filter" not in html and "pk-block__count" not in html
    assert "Δ к" not in html and "отз." not in html


@pytest.mark.parametrize("code", ["IQ", "MD", "GB", "CN", "VN", "US", "DE", "AE", "QA"])
def test_страны_из_данных_называются_словом(code: str) -> None:
    assert code in COUNTRY_NAMES
    assert country_title(code, "ru") != code and country_title(code, "en") != code
