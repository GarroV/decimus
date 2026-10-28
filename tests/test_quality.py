"""Расчёты «Качества»: средние КР, карт и агрегаторов — правдоподобное неверное число вместо сбоя.

Числа посчитаны руками; взвешивание — решения владельца (D673, D676), сводной оценки нет (D677).
"""

from __future__ import annotations

from decimal import Decimal as D

from src.domain import quality as q


def test_five_point_scale_conversion() -> None:
    assert q.five_point(D("8.6"), 10) == D("4.3")  # Wolt
    assert q.five_point(D("92"), 100) == D("4.6")  # Glovo, проценты
    assert q.five_point(D("4.2"), 5) == D("4.2")


def test_kr_is_count_weighted_mean_of_dine_in_and_delivery() -> None:
    # (4.0*10 + 5.0*30) / 40 = 4.75
    assert q.combine_kr(D("4.0"), 10, D("5.0"), 30) == D("4.75")
    assert q.combine_kr(D("4.0"), 10, None, 0) == D("4.0")
    assert q.combine_kr(None, 0, D("4.5"), 7) == D("4.5")
    assert q.combine_kr(None, 0, None, 0) is None
    # оценка без отзывов — не данные
    assert q.combine_kr(D("4.0"), 0, D("5.0"), 0) is None


def test_maps_score_is_mean_weighted_by_rating_counts() -> None:
    # решение владельца 28.10.2026: средневзвешенная по числу оценок
    assert q.maps_score([(D("4.0"), 300), (D("5.0"), 100)]) == D("4.25")
    assert q.maps_score([(D("4.4"), 12)]) == D("4.4")
    assert q.maps_score([(D("4.4"), 0), (D("3.0"), 0)]) is None
    assert q.maps_score([(D("4.4"), 0), (D("3.0"), 10)]) == D("3.0")
    assert q.maps_score([]) is None


def test_aggregator_score_is_weighted_by_orders_of_rated_aggregators() -> None:
    # Wolt 100 заказов 4.0, Glovo 300 заказов 5.0, Bolt 50 заказов без оценки
    score = q.aggregator_score([(D("4.0"), 100), (D("5.0"), 300), (None, 50)])
    assert score == D("4.75")
    assert q.aggregator_score([(None, 10)]) is None
    assert q.aggregator_score([(D("4.0"), 0)]) is None
    assert q.aggregator_score([]) is None


def test_aggregator_score_renormalises_over_rated_aggregators() -> None:
    # Словения у аналитика: Wolt 9.8 из 10 на 41 985 заказов, Ehrana 500 заказов без оценки
    wolt = q.five_point(D("9.8"), 10)
    assert q.aggregator_score([(wolt, 41985), (None, 500)]) == D("4.90")
    # две площадки с оценкой: Wolt 9.0/10 ×300 и Glovo 90% ×100 — обе 4.5
    two = q.aggregator_score([(q.five_point(D("9.0"), 10), 300), (q.five_point(D("90"), 100), 100)])
    assert two == D("4.5")
    # Bolt 4.0/5 ×100 и Wolt 10/10 ×300: 0.25 × 4 + 0.75 × 5
    mixed = q.aggregator_score([(q.five_point(D("4.0"), 5), 100), (q.five_point(D("10"), 10), 300)])
    assert mixed == D("4.75")


def test_mean_and_share() -> None:
    assert q.mean([D("1"), D("2")]) == D("1.5")
    assert q.mean([]) is None
    assert q.share(1, 4) == D("0.25")
    assert q.share(0, 0) is None
    assert q.Orders(3, 2, 1).total == 6
