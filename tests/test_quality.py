"""Расчёты «Качества»: средние КР, карт и агрегаторов — правдоподобное неверное число вместо сбоя.

Числа посчитаны руками; взвешивание — решения владельца (D673, D676), сводной оценки нет (D677).
"""

from __future__ import annotations

from decimal import Decimal as D

import pytest

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


def _r(value: D | None, places: str = "0.001") -> D | None:
    return None if value is None else value.quantize(D(places))


@pytest.mark.parametrize(
    ("checks", "weight"),
    [
        (None, "0"),
        (D("0"), "0"),
        (D("0.5"), "0.1"),
        (D("1.99"), "0.1"),
        (D("2"), "0.3"),
        (D("4.99"), "0.3"),
        (D("5"), "0.5"),
        (D("12"), "0.5"),
    ],
)
def test_rko_weight_thresholds(checks: D | None, weight: str) -> None:
    assert q.rko_weight(checks) == D(weight)


def test_poland_example_from_analyst() -> None:
    r = q.overall(
        rko=D("90.89"),
        rko_checks_per_week=D("4.44"),
        kr=D("4.65"),
        maps=D("4.38"),
        aggregators=D("4.10"),
        orders=q.Orders(aggregators=35, app_site=25, other=40),
    )
    assert r.rko5 == D("4.5445")
    assert r.weights.rko == D("0.3")
    assert _r(r.weights.kr, "0.0001") == D("0.2083")
    assert r.weights.maps == D("0.2")
    assert _r(r.weights.aggregators, "0.0001") == D("0.2917")
    assert r.weights.total == 1
    assert not r.incomplete
    assert _r(r.score) == D("4.404")


def test_bulgaria_example_weights_sum_to_100() -> None:
    # инструкция: 50% + 23% + 20% + 7% = 100%
    r = q.overall(
        rko=D("95"),
        rko_checks_per_week=D("6"),
        kr=D("4.7"),
        maps=D("4.5"),
        aggregators=D("4.2"),
        orders=q.Orders(aggregators=9, app_site=32, other=59),
    )
    assert r.weights.rko == D("0.5")
    assert _r(r.weights.kr, "0.001") == D("0.234")
    assert _r(r.weights.aggregators, "0.001") == D("0.066")
    assert r.weights.total == 1
    expected = D("0.5") * D("4.75") + r.weights.kr * D("4.7") + D("0.2") * D("4.5")
    assert _r(r.score) == _r(expected + r.weights.aggregators * D("4.2"))


def test_no_digital_orders_renormalises_over_rko_and_maps() -> None:
    r = q.overall(
        rko=D("90"),
        rko_checks_per_week=D("3"),
        kr=D("4.5"),
        maps=D("4.4"),
        aggregators=D("4.0"),
        orders=q.Orders(aggregators=0, app_site=0, other=80),
    )
    assert (r.weights.kr, r.weights.aggregators) == (0, 0)
    assert r.weights.total == D("0.5")
    assert r.incomplete
    # (0.3 × 4.5 + 0.2 × 4.4) / 0.5
    assert _r(r.score) == D("4.460")


def test_missing_kr_drops_its_weight_and_renormalises() -> None:
    r = q.overall(
        rko=D("90"),
        rko_checks_per_week=D("5"),
        kr=None,
        maps=D("4.0"),
        aggregators=D("4.0"),
        orders=q.Orders(aggregators=50, app_site=50, other=0),
    )
    assert r.weights.kr == 0
    assert _r(r.weights.aggregators) == D("0.150")
    assert r.incomplete
    assert _r(r.score) == _r((D("0.5") * D("4.5") + D("0.2") * 4 + D("0.15") * 4) / D("0.85"))


def test_only_maps_gives_maps_score() -> None:
    r = q.overall(
        rko=None,
        rko_checks_per_week=None,
        kr=None,
        maps=D("4.68"),
        aggregators=D("4.51"),
        orders=q.Orders(0, 0, 0),
    )
    assert r.weights == q.Weights(D(0), D(0), D("0.2"), D(0))
    assert r.score == D("4.68")
    assert r.incomplete


def test_nothing_known_gives_no_score() -> None:
    r = q.overall(
        rko=None,
        rko_checks_per_week=D("6"),
        kr=None,
        maps=None,
        aggregators=None,
        orders=q.Orders(0, 0, 0),
    )
    assert r.score is None
    assert not r.incomplete
