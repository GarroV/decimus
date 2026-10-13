"""Расчёты сводки рейтингов (ядро): средние, дельта, Top/Bottom, нарушения, зона риска.

Цифры этой страницы читают как факт про партнёра — сбой здесь молчит.
"""

from __future__ import annotations

import math
from dataclasses import replace
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
    assert total.rs_delta == -1.7  # 85 - 86.67, до одного знака
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


def test_нарушения_без_числа_проверок_данные_есть_без_доли() -> None:
    """РС из таблицы контроля (D464) несёт нарушения, но не число проверок: это не «нет данных»."""
    block = violation_block([v("A", 2)], checkups=0)
    assert (block.total, block.per_checkup, block.has_data) == (2, None, True)
    assert violation_block([], checkups=0).has_data is False
    assert violation_block([], checkups=3).has_data is True


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


def test_дельта_равных_средних_без_шума_и_минус_нуля() -> None:
    cur = [f("a", "SI", 99.6), f("b", "SI", 99.8)]
    prev = [f("a", "SI", 99.7), f("b", "SI", 99.7)]
    result = score_lines(cur, prev, ["SI"])[1].rs_delta
    assert result == 0.0 and math.copysign(1, result) > 0


def test_хард_пометка_автодетекции_и_пробелы_не_мешают() -> None:
    rules = [HardRule("rko", "text", "Пиццу привезли холодной")]
    facts = [
        v("Пиццу привезли  холодной (ML)", category="other"),
        v("Пиццу привезли холодной (ИИ)"),
    ]
    assert len(hard_lines(facts, rules, "rko")) == 2


def test_нарушение_с_пометкой_и_без_одно_в_топе() -> None:
    block = violation_block([v("A (ML)", 2), v("A", 1), v("B", 1)], checkups=1)
    assert [(line.text, line.count) for line in block.top] == [("A", 3), ("B", 1)]


def test_contains_с_начала_слова() -> None:
    rules = [HardRule("rs", "contains", "критичн"), HardRule("rs", "contains", "D3")]
    assert not hard_lines([v("x", parent="Некритичные нарушения")], rules[:1], "rs")
    assert hard_lines([v("x", parent="Критичные нарушения")], rules[:1], "rs")
    assert hard_lines([v("x", parent="Уровень D3")], rules[1:], "rs")


def test_равные_балл_и_имя_порядок_по_коду() -> None:
    facts = [Fact(u, "Same", "SI", "rs", 1, date(2026, 7, 1), 90.0) for u in ("z", "m", "a")]
    top, _ = top_bottom(facts, "rs", threshold=85)
    assert [u.unit for u in top] == ["a", "m", "z"]


def test_хард_порядок_не_зависит_от_входа() -> None:
    rules = [HardRule("rs", "contains", "D3")]
    a, b = v("T", parent="D3", unit="a"), v("T", parent="D3", unit="b")
    a, b = replace(a, unit_name="Same"), replace(b, unit_name="Same")
    assert hard_lines([b, a], rules, "rs") == hard_lines([a, b], rules, "rs")


def test_страны_вне_списка_не_входят_в_группу() -> None:
    facts = [f("a", "SI", 90), f("c", "RS", 10)]
    assert group_average(facts, "rs", ["SI"]) == pytest.approx(90)


def test_граница_top_bottom_по_показанному_значению() -> None:
    """85.04 на экране «85.0» — ровно порог, значит Bottom, а не «Выше 85» (P38)."""
    top, bottom = top_bottom([f("a", "SI", 85.04), f("b", "SI", 85.06)], "rs", threshold=85)
    assert [u.unit for u in top] == ["b"]
    assert [u.unit for u in bottom] == ["a"]


def test_зона_риска_по_показанному_значению() -> None:
    """84.96 на экране «85.0» — не ниже порога 85, в зону риска не идёт (P38)."""
    facts = [f("a", "SI", 84.96, period=p) for p in (1, 2)] + [
        f("b", "SI", 84.94, period=p) for p in (1, 2)
    ]
    zone = risk_zone(facts, [1, 2], rating_type="rs", threshold=85)
    assert [u.unit for u in zone] == ["b"]


def test_точка_графика_на_каждый_период_рейтинга() -> None:
    """D396: точка графика — период рейтинга; средняя за период — по пиццериям
    (D353), с датами периода для подписи под графиком; старые первыми."""
    from datetime import date

    from src.ratings.summary import Fact, Point, points

    def f(unit: str, country: str, pid: int, day: date, score: float) -> Fact:
        return Fact(unit, unit, country, "rs", pid, day, score, date(day.year, day.month, 15))

    факты = [
        f("a", "RS", 2, date(2026, 9, 1), 96), f("b", "RS", 2, date(2026, 9, 1), 70),
        f("a", "RS", 1, date(2026, 8, 1), 90), f("b", "RS", 1, date(2026, 8, 1), 80),
        f("c", "NG", 2, date(2026, 9, 1), 10),  # чужая страна в группу не входит
    ]  # fmt: skip

    assert points(факты, "rs", ["RS"]) == (
        Point(date(2026, 8, 1), date(2026, 8, 15), 85, 2),
        Point(date(2026, 9, 1), date(2026, 9, 15), 83, 2),
    )
    assert points(факты, "rko", ["RS"]) == ()


def test_кластер_IMF_делит_страны_по_справочнику() -> None:
    from datetime import date

    from src.db.ratings_read import CountryRow
    from src.ratings.periods import ReportPeriod
    from src.ratings.report import Choices, GroupLine, Selection, group_countries, group_lines
    from src.ratings.summary import Fact

    страны = (
        CountryRow("RS", "Сербия", "Serbia", None, True, "CEE"),
        CountryRow("NG", "Нигерия", "Nigeria", None, True, "OTHER"),
    )
    found = Choices((), страны, ())
    период = ReportPeriod("month", "2026-09", date(2026, 9, 1), date(2026, 9, 30))
    факты = [Fact("a", "a", "RS", "rs", 1, date(2026, 9, 2), 90.0),
             Fact("b", "b", "NG", "rs", 1, date(2026, 9, 2), 70.0)]  # fmt: skip

    imf = group_lines(Selection("imf", None, период), found, ("RS", "NG"), (факты, []))
    assert [(g.key, g.countries, g.rs) for g in imf] == [
        ("CEE", ("RS",), 90.0),
        ("OTHER", ("NG",), 70.0),
    ]

    кластер = Selection("cluster", "OTHER", период)
    assert group_countries(кластер, страны) == ("NG",)
    one = group_lines(кластер, found, ("NG",), (факты, []))
    assert [(g.key, g.rs) for g in one] == [(None, 70.0)]
    assert isinstance(one[0], GroupLine)


def test_девелопер_общая_строка_и_по_стране() -> None:
    """D385: срез девелопера — общая строка по всем его странам и строка на страну."""
    from datetime import date

    from src.db.ratings_read import CountryRow
    from src.ratings.periods import ReportPeriod
    from src.ratings.report import Choices, Selection, group_lines
    from src.ratings.summary import Fact

    страны = (
        CountryRow("RS", "Сербия", "Serbia", "Dev", True, "CEE"),
        CountryRow("SI", "Словения", "Slovenia", "Dev", True, "CEE"),
    )
    период = ReportPeriod("month", "2026-09", date(2026, 9, 1), date(2026, 9, 30))
    факты = [Fact("a", "a", "RS", "rs", 1, date(2026, 9, 2), 90.0),
             Fact("b", "b", "SI", "rs", 1, date(2026, 9, 2), 70.0)]  # fmt: skip
    строки = group_lines(
        Selection("developer", "Dev", период), Choices(("Dev",), страны, ()), ("RS", "SI"),
        (факты, []),
    )  # fmt: skip
    assert [(g.level, g.key, g.rs) for g in строки] == [
        ("slice", None, 80.0), ("country", "RS", 90.0), ("country", "SI", 70.0),
    ]  # fmt: skip


def test_у_пиццерии_top_bottom_изменение_к_прошлому_периоду() -> None:
    """Треугольник у пиццерии (11.10.2026): средняя пиццерии за период минус её
    средняя за прошлый; не было в прошлом — изменения нет, а не «+всё»."""
    прошлый = [*ПРОШЛЫЙ, f("a", "SI", 70, kind="rko")]
    top, bottom = top_bottom(ТЕКУЩИЙ, "rs", threshold=85, previous=прошлый)
    by = {u.unit: u.delta for u in top + bottom}
    assert by == {"c": 0.0, "b": -10.0, "a": 5.0}
    _, rko = top_bottom(ТЕКУЩИЙ, "rko", threshold=95, previous=прошлый)
    assert [(u.unit, u.delta) for u in rko] == [("a", 23.0)]  # РКО сравнивается с РКО
    новые, _ = top_bottom([f("d", "SI", 99)], "rs", threshold=85, previous=прошлый)
    assert новые[0].delta is None
    без_прошлого, _ = top_bottom(ТЕКУЩИЙ, "rs", threshold=85)
    assert без_прошлого[0].delta is None
