"""Период «Рейтингов» (D630): списки РС и недель РКО; шапка со значком «?» (D631)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from flask import render_template_string
from test_web_ratings_tiles import _клиент, _страница
from web_harness import собрать

from src.ratings import freshness as fresh
from src.ratings import periods as rp
from src.web import ratings as screen
from src.web import ratings_calendar as cal

РС = (
    rp.RatingPeriod(11, date(2026, 9, 1), date(2026, 9, 15), "Сентябрь 1", "September 1"),
    rp.RatingPeriod(12, date(2026, 9, 16), date(2026, 9, 30), "Сентябрь 2", "September 2"),
    rp.RatingPeriod(13, date(2026, 10, 1), date(2026, 10, 15), "Октябрь 1", "October 1"),
)
РКО = (
    rp.RatingPeriod(21, date(2026, 10, 5), date(2026, 10, 11), "Неделя 41", "Week 41"),
    rp.RatingPeriod(22, date(2026, 10, 12), date(2026, 10, 18), "Неделя 42", "Week 42"),
)
МЕСЯЦЫ = (date(2026, 9, 1), date(2026, 10, 1))


def _построить(key: str, lang: str = "ru") -> cal.Calendar:
    период = rp.parse_period(key, rs_periods=РС)
    assert период is not None
    return cal.build(период, МЕСЯЦЫ, РС, lang, РКО)


def test_неделя_рко_узнаётся_по_отрезку_и_выбрана_в_своём_списке() -> None:
    c = _построить("2026-10-12..2026-10-18")

    assert c.title == "12.10 — 18.10.2026"
    assert [o.key for o in c.rko_options if o.on] == ["2026-10-12..2026-10-18"]
    assert not any(o.on for o in c.rs_options)


def test_периоды_рс_по_убыванию_с_именами_и_выбран_совпавший() -> None:
    c = _построить("rs:12", "ru")

    assert [o.title for o in c.rs_options] == ["Октябрь 1", "Сентябрь 2", "Сентябрь 1"]
    assert [o.key for o in c.rs_options if o.on] == ["rs:12"]
    assert c.title == "Сентябрь 2"
    assert _построить("rs:12", "en").rs_options[0].title == "October 1"


def test_отрезок_календаря_совпал_с_периодом_рс_выбирает_его_в_списке() -> None:
    c = _построить("2026-09-16..2026-09-30")

    assert [o.key for o in c.rs_options if o.on] == ["rs:12"]


def test_недели_рко_по_убыванию_ключ_это_обычный_отрезок() -> None:
    c = _построить("2026-10-12..2026-10-18")

    assert [o.key for o in c.rko_options] == ["2026-10-12..2026-10-18", "2026-10-05..2026-10-11"]


def test_произвольный_отрезок_не_выбирает_ничего_и_называется_датами() -> None:
    c = _построить("2026-10-02..2026-10-09")

    assert c.title == "02.10.2026 — 09.10.2026"
    assert not any(o.on for o in (*c.rs_options, *c.rko_options))


def test_стрелка_недели_рко_листает_на_неделю() -> None:
    c = _построить("2026-10-05..2026-10-11")

    assert c.next == "2026-10-12..2026-10-18"
    assert c.prev == "2026-09-28..2026-10-04"


_ХОСТ = (
    '{% from "ratings/_period.html" import period_lists with context %}'
    "{% macro href(g, v, k) %}/r?period={{ k }}{% endmacro %}"
    "{{ period_lists(c, href, 'imf', none) }}"
)


def test_списки_в_окне_периода_выбран_пункт_и_заглушка_без_совпадения() -> None:
    app = собрать(tenant="HQ")
    with app.test_request_context("/?lang=ru"):
        совпал = render_template_string(_ХОСТ, c=_построить("2026-10-12..2026-10-18"))
        мимо = render_template_string(_ХОСТ, c=_построить("2026-10-02..2026-10-09"))

    assert совпал.count("data-pick-nav") == 2
    assert (
        '<option value="/r?period=2026-10-12..2026-10-18" selected>12.10 — 18.10.2026</option>'
        in совпал
    )
    assert "disabled>Выбрать…</option>" in совпал  # в списке РС заглушка: неделя — не период РС
    assert совпал.count("disabled>") == 1
    assert мимо.count("disabled>Выбрать…</option>") == 2
    assert "<noscript>" in совпал


def _шапка_экрана(monkeypatch: pytest.MonkeyPatch, rows: tuple[fresh.Row, ...]) -> str:
    """Шапка живого экрана «Рейтинги» с заданными строками свежести источников."""
    _страница(monkeypatch, 0)
    monkeypatch.setattr(screen.ratings_freshness, "read_rows", lambda now: rows)
    for client in _клиент(monkeypatch):
        страница = client.get("/ratings?lang=ru").get_data(as_text=True)
        начало = страница.index('<header class="rt-head">')
        return страница[начало : страница.index("</header>", начало)]
    raise AssertionError("клиент не создан")


def test_шапка_свежесть_таблицей_с_точкой_и_словом_у_каждой_строки(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        fresh.Row(
            "rs",
            fresh.Status.FRESH,
            begin_on=date(2026, 10, 1),
            end_on=date(2026, 10, 15),
            arrived=datetime(2026, 10, 22, 8, 9, tzinfo=UTC),
        ),
        fresh.Row(
            "agg", fresh.Status.STALE, "yandex_eda", arrived=datetime(2026, 10, 11, tzinfo=UTC)
        ),
    )

    html = _шапка_экрана(monkeypatch, rows)

    assert 'aria-label="Когда обновлены данные: устарели"' in html  # худшая точка — и словом
    assert html.count("<tr>") == 3  # заголовок и две строки, порядок задан
    assert "за 1–15.10" in html and "22.10 08:09" in html and "Яндекс Еда" in html
    assert 'class="rt-fdot rt-fdot--fresh"' in html and 'class="rt-fdot rt-fdot--stale"' in html
    assert "свежие</span>" in html and "устарели</span>" in html  # цвет — не единственный признак
    assert " · " not in html


def test_шапка_без_источников_говорит_это_одной_строкой(monkeypatch: pytest.MonkeyPatch) -> None:
    html = _шапка_экрана(monkeypatch, ())

    assert "<table" not in html and "Загрузок ещё не было." in html
