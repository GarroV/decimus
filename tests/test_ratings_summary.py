"""Расчёты сводки рейтингов (ядро): средние, дельта, Top/Bottom, нарушения, зона риска.

Цифры этой страницы читают как факт про партнёра — сбой здесь молчит.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.ratings.summary import (
    Fact,
    HardRule,
    ViolationFact,
    country_average,
    delta,
    group_average,
    hard_lines,
    risk_zone,
    score_lines,
    top_bottom,
    violation_block,
)


def f(unit: str, country: str, score: float, *, kind: str = "rs", period: int = 1) -> Fact:
    return Fact(unit, unit.upper(), country, kind, period, date(2026, 7, period), score)


ТЕКУЩИЙ = [
    f("a", "SI", 90, period=1),
    f("a", "SI", 80, period=2),  # a: 85
    f("b", "SI", 70, period=1),  # b: 70
    f("c", "RS", 100, period=1),  # c: 100
    f("a", "SI", 93, kind="rko", period=1),
]
ПРОШЛЫЙ = [f("a", "SI", 80), f("b", "SI", 80), f("c", "RS", 100)]


def test_страна_среднее_пиццерий_группа_среднее_всех() -> None:
    assert country_average(ТЕКУЩИЙ, "rs", "SI") == pytest.approx(77.5)
    assert group_average(ТЕКУЩИЙ, "rs", ["SI", "RS"]) == pytest.approx(85.0)
    assert country_average(ТЕКУЩИЙ, "rs", "BG") is None


def test_дельта_к_прошлому_периоду() -> None:
    lines, total = score_lines(ТЕКУЩИЙ, ПРОШЛЫЙ, ["SI", "RS", "BG"])
    by = {line.country: line for line in lines}
    assert by["SI"].rs == pytest.approx(77.5) and by["SI"].rs_delta == pytest.approx(-2.5)
    assert by["SI"].rko == pytest.approx(93) and by["SI"].rko_delta is None
    assert by["RS"].rs_delta == pytest.approx(0.0)
    assert by["BG"].rs is None and by["BG"].rs_delta is None
    assert total.country == "" and total.rs == pytest.approx(85.0)
    assert total.rs_delta == pytest.approx(85.0 - (80 + 80 + 100) / 3)
    assert delta(None, 80) is None
    assert delta(80, None) is None
    assert delta(70, 80) == pytest.approx(-10)


def test_top_выше_порога_bottom_не_выше() -> None:
    top, bottom = top_bottom(ТЕКУЩИЙ, "rs", threshold=85)
    assert [u.unit for u in top] == ["c"]
    assert [u.unit for u in bottom] == ["b", "a"]  # 70, затем 85 — ровно порог идёт вниз


def test_top_bottom_по_десять() -> None:
    много = [f(f"u{n:02d}", "SI", 86 + n % 10) for n in range(15)]
    top, _ = top_bottom(много, "rs", threshold=85)
    assert len(top) == 10 and top[0].score >= top[-1].score


def test_bottom_ограничен_десятью_худшими() -> None:
    много = [f(f"u{n:02d}", "SI", 50 + n) for n in range(15)]
    _, bottom = top_bottom(много, "rs", threshold=85)
    assert [u.unit for u in bottom] == [f"u{n:02d}" for n in range(10)]


def v(
    text: str,
    amount: int = 1,
    *,
    category: str = "violation",
    parent: str | None = None,
    country: str = "SI",
    unit: str = "a",
) -> ViolationFact:
    return ViolationFact(unit, unit.upper(), country, text, parent, category, amount)


def test_топ5_и_на_одну_проверку() -> None:
    facts = [
        v("A", 3),
        v("B", 2),
        v("C"),
        v("D"),
        v("E"),
        v("F"),
        v("Пиццу привезли холодной", category="other"),
    ]
    block = violation_block(facts, checkups=4)
    assert block.total == 9
    assert block.per_checkup == pytest.approx(2.25)
    assert [(line.text, line.count) for line in block.top] == [
        ("A", 3),
        ("B", 2),
        ("C", 1),
        ("D", 1),
        ("E", 1),
    ]


def test_замечание_считается_наравне_с_нарушением() -> None:
    block = violation_block([v("A"), v("B", category="remark")], checkups=1)
    assert block.total == 2


def test_ноль_проверок_не_деление_на_ноль() -> None:
    block = violation_block([], checkups=0)
    assert (block.total, block.per_checkup, block.top) == (0, None, ())
    assert block.checkups == 0  # «нет данных» отличимо от «нарушений нет»


def test_хард_по_тексту_и_по_подстроке_родителя() -> None:
    rules = [HardRule("rko", "text", "пиццу привезли холодной"), HardRule("rs", "contains", "D3")]
    facts = [
        v("Пиццу привезли холодной", category="other"),
        v("Грязь", parent="Уровень D3"),
        v("Грязь"),
    ]
    assert [x.text for x in hard_lines(facts, rules, "rko")] == ["Пиццу привезли холодной"]
    assert [x.parent_name for x in hard_lines(facts, rules, "rs")] == ["Уровень D3"]


def test_зона_риска_три_подряд_строго_ниже() -> None:
    facts = [
        f("a", "SI", 80, period=1),
        f("a", "SI", 84, period=2),
        f("a", "SI", 70, period=3),
        f("b", "SI", 80, period=1),
        f("b", "SI", 90, period=2),
        f("b", "SI", 70, period=3),
        f("c", "SI", 80, period=1),
        f("c", "SI", 70, period=3),
        f("d", "SI", 84, period=1),
        f("d", "SI", 85, period=2),
        f("d", "SI", 84, period=3),
    ]
    zone = risk_zone(facts, [1, 2, 3], rating_type="rs", threshold=85)
    assert [(u.unit, u.scores) for u in zone] == [("a", (80.0, 84.0, 70.0))]


def test_зона_риска_без_полного_окна_пуста() -> None:
    assert risk_zone([f("a", "SI", 50)], [1, 2], rating_type="rs", threshold=85) == ()
