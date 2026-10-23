"""Период «Рейтингов» (D630): списки РС и недель РКО; шапка со значком «?» (D631)."""

from __future__ import annotations

from datetime import date, datetime

from flask import render_template_string
from web_harness import собрать

from src.ratings import periods as rp
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


_ШАПКА = (
    '{% from "ratings/_loaded.html" import loaded_hint with context %}'
    "{{ loaded_hint(last, '%d.%m.%Y %H:%M') }}"
)


def test_шапка_свежесть_столбиком_под_знаком_вопроса_без_перечня_через_точку() -> None:
    app = собрать(tenant="HQ")
    last = {
        "snapshot": datetime(2026, 10, 20, 9, 5),
        "rko-evaluations": datetime(2026, 10, 21, 18, 40),
    }
    with app.test_request_context("/?lang=ru"):
        html = render_template_string(_ШАПКА, last=last)
        пусто = render_template_string(_ШАПКА, last={})

    assert 'aria-label="Когда обновлены данные"' in html
    assert "Последняя загрузка" in html
    assert html.count("<li>") == 2
    assert "20.10.2026 09:05</li>" in html and "21.10.2026 18:40</li>" in html
    assert " · " not in html
    assert "Загрузок ещё не было." in пусто
    assert "<li>" not in пусто
