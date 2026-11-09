"""Карта за месяц по поштучным оценкам (D732, D733): среднее месяца, порог 10%, перенос.

Числа посчитаны руками. Пример владельца: июнь, июль, август — 3,2 / 3,3 / 3,2 при обычном числе
оценок; в сентябре одна оценка 5 — сентябрь берёт значение августа.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

from src.domain import maps_month as mm

JUN, JUL, AUG, SEP, OCT = (date(2026, m, 1) for m in (6, 7, 8, 9, 10))


def _month(avg: str, count: int) -> mm.MonthStat:
    """Месяц с `count` оценками и средним `avg`."""
    return mm.MonthStat(count, D(avg) * count)


def test_raw_value_is_arithmetic_mean_of_the_months_ratings() -> None:
    stats = {AUG: mm.MonthStat(4, D(5 + 4 + 4 + 3))}  # 16 / 4 = 4
    got = mm.month_value(stats, AUG, floor=AUG)
    assert got == mm.MonthValue(D(4), 4, None)


def test_owners_example_one_five_star_in_september_is_not_taken_on_faith() -> None:
    stats = {
        JUN: _month("3.2", 40),
        JUL: _month("3.3", 40),
        AUG: _month("3.2", 40),
        SEP: mm.MonthStat(1, D(5)),
    }
    got = mm.month_value(stats, SEP, floor=JUN)
    assert got == mm.MonthValue(D("3.2"), 40, AUG)  # значение и вес августа, пометка «перенесено»


def test_threshold_is_ten_percent_of_mean_of_three_previous_months() -> None:
    prev = {JUN: _month("4", 30), JUL: _month("4", 30), AUG: _month("4", 30)}  # среднее 30, порог 3
    below = {**prev, SEP: mm.MonthStat(2, D(10))}
    exactly = {**prev, SEP: mm.MonthStat(3, D(15))}
    assert mm.month_value(below, SEP, floor=JUN) == mm.MonthValue(D(4), 30, AUG)
    assert mm.month_value(exactly, SEP, floor=JUN) == mm.MonthValue(D(5), 3, None)


def test_mean_uses_only_three_months_before_not_older_ones() -> None:
    stats = {
        date(2026, 1, 1): _month("4", 1000),  # старше трёх месяцев — среднее не двигает
        JUN: _month("4", 10),
        JUL: _month("4", 10),
        AUG: _month("4", 10),
        SEP: mm.MonthStat(1, D(5)),  # порог 1: ровно 10% от 10
    }
    assert mm.month_value(stats, SEP, floor=date(2026, 1, 1)) == mm.MonthValue(D(5), 1, None)


def test_month_without_ratings_takes_previous_months_value() -> None:
    stats = {JUL: _month("3.5", 20), AUG: _month("4", 20)}
    assert mm.month_value(stats, SEP, floor=JUL) == mm.MonthValue(D(4), 20, AUG)


def test_carry_is_recursive_and_points_at_the_month_the_value_came_from() -> None:
    stats = {JUL: _month("3.5", 20), AUG: _month("4", 20)}
    got = mm.month_value(stats, OCT, floor=JUL)  # сентябрь пуст, октябрь пуст
    assert got == mm.MonthValue(D(4), 20, AUG)


def test_rejected_month_does_not_lower_the_average_for_the_next_one() -> None:
    # сентябрь отвергнут, но в среднее октября входит сырое число оценок (1), а не вес переноса
    stats = {
        JUN: _month("4", 30),
        JUL: _month("4", 30),
        AUG: _month("4", 30),
        SEP: mm.MonthStat(1, D(5)),
        OCT: mm.MonthStat(10, D(30)),  # среднее июль-сен = (30+30+1)/3 ≈ 20,3, порог 2,03
    }
    assert mm.month_value(stats, OCT, floor=JUN) == mm.MonthValue(D(3), 10, None)


def test_no_history_means_no_value() -> None:
    assert mm.month_value({}, SEP, floor=SEP) is None
    # перенос не идёт глубже загруженной истории
    stats = {JUN: _month("4", 20)}
    assert mm.month_value(stats, SEP, floor=JUL) is None


def test_first_month_of_history_with_ratings_is_accepted_without_previous_months() -> None:
    stats = {JUN: mm.MonthStat(1, D(5))}
    assert mm.month_value(stats, JUN, floor=JUN) == mm.MonthValue(D(5), 1, None)


def test_only_months_inside_history_form_the_average() -> None:
    # история начинается в августе: среднее — по одному августу (20), порог 2
    stats = {AUG: _month("4", 20), SEP: mm.MonthStat(1, D(5))}
    assert mm.month_value(stats, SEP, floor=AUG) == mm.MonthValue(D(4), 20, AUG)
