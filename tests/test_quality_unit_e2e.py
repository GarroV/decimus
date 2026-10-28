"""ЛКО одной пиццерии от входов Dodo IS до числа: Любляна-1, сентябрь 2026.

Входы — живые формы ответов, сверенные 28.10.2026 (РКО и РС из `controlling`, КР из
`customer-ratings`, заказы из `finances/sales/units` и `accounting/sales`), плюс карты и
оценка Wolt. Ядро: ошибка здесь даёт правдоподобное неверное число на экране.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D

from src.db import dodois_metrics as dm
from src.domain import dodois_metrics as parse
from src.web import quality_data

U = "000d3a23750ca95c11e915ab0763c302"
SEPTEMBER = date(2026, 9, 1)


def _rko(start: str, rate: str, checks: int | None) -> dm.UnitRatingPeriod:
    first = date.fromisoformat(start)
    return dm.UnitRatingPeriod(
        U, "rko", first, first + timedelta(days=6), D(rate), "Published", checks
    )


def _rs(start: str, stop: str, rate: str) -> dm.UnitRatingPeriod:
    return dm.UnitRatingPeriod(
        U, "rs", date.fromisoformat(start), date.fromisoformat(stop), D(rate), "Published", None
    )


def _history() -> list[dm.UnitRatingPeriod]:
    return [
        _rko("2026-08-31", "83.5", None),
        _rko("2026-09-07", "93.25", 5),
        _rko("2026-09-14", "94.0", 5),
        _rko("2026-09-21", "92.25", 6),
        _rko("2026-09-28", "84.33", 2),
        _rs("2026-08-31", "2026-09-13", "92.0"),
        _rs("2026-09-14", "2026-10-04", "88.0"),
    ]


def _in_month(periods: list[dm.UnitRatingPeriod], month: date) -> list[dm.UnitRatingPeriod]:
    """То, что отдаёт чтение за месяц: РКО по началу недели, РС — по большинству дней."""
    return [p for p in periods if parse.rating_month(p.kind, p.period_from, p.period_to) == month]


def _sales() -> list[dm.UnitSales]:
    rows = [
        ("Aggregator", "Delivery", "8000", 320),
        ("Aggregator", "Dine-in", "20225.5", 1075),
        ("MobileApp", "Dine-in", "10526.34", 583),
        ("MobileApp", "Delivery", "3389.97", 133),
        ("Dine-in", "Dine-in", "16225.34", 1632),
        ("Kiosk", "Dine-in", "7681.04", 440),
        ("Manager", "Dine-in", "2189.66", 57),
        ("CallCenter", "Delivery", "3107.15", 118),
        ("Website", "Delivery", "1535.04", 64),
    ]
    return [dm.UnitSales(U, s, c, n, D(v), "EUR") for s, c, v, n in rows]


def _unit(agg_scores: dict[str, tuple[D, int]]) -> quality_data.UnitQuality:
    return quality_data._unit(
        U,
        "Ljubljana-1",
        "SI",
        scores=[],
        audit=None,
        maps=(("Google", D("4.40"), 1113),),
        sales=_sales(),
        agg_orders=[
            dm.UnitAggregatorOrders(U, "Wolt", 1380, None),
            dm.UnitAggregatorOrders(U, "Ehrana", 13, None),
        ],
        kr=dm.UnitKr(U, D("4.79"), 58, D("4.73"), 144),
        agg_scores=agg_scores,
        periods=_in_month(_history(), SEPTEMBER),
    )


def test_rs_period_goes_to_the_month_holding_most_of_its_days() -> None:
    sept = _in_month(_history(), SEPTEMBER)

    assert sorted(p.period_from.isoformat() for p in sept if p.kind == "rs") == [
        "2026-08-31",
        "2026-09-14",
    ]
    # Неделя РКО с началом 31.08 остаётся августу, как в таблице контроля.
    assert date(2026, 8, 31) not in {p.period_from for p in sept if p.kind == "rko"}
    assert parse.rating_month("rs", date(2026, 9, 14), date(2026, 10, 4)) == SEPTEMBER
    assert parse.rating_month("rs", date(2026, 9, 28), date(2026, 10, 11)) == date(2026, 10, 1)


def test_ljubljana_1_september_lko_with_wolt_score() -> None:
    unit = _unit({"wolt": (D("9.0"), 10)})

    assert unit.rko == D("90.9575")  # среднее четырёх недель с началом 07.09–28.09
    assert unit.rko_checks == D("4.5")
    assert unit.es.rs == D("90")  # (92 + 88) / 2
    w = unit.lko.weights
    assert w.rko == D("0.3")
    assert w.maps == D("0.2")
    assert round(w.kr, 6) == D("0.179310")
    assert round(w.aggregators, 6) == D("0.320690")
    assert unit.lko.weight_sum.quantize(D("0.000001")) == D("1.000000")
    assert not unit.lko.sum_below_full
    assert round(unit.lko.scores.kr or D(0), 6) == D("4.747228")
    assert unit.lko.scores.aggregators == D("4.5")  # Wolt 9/10; Ehrana без оценки не в счёт
    assert unit.lko.score is not None
    assert abs(unit.lko.score - D("4.539")) < D("0.001")


def test_ljubljana_1_september_without_aggregator_score_warns_about_weights() -> None:
    unit = _unit({})  # у Словении оценки Wolt начинаются с 11.10: за сентябрь их нет нигде

    assert unit.lko.weights.aggregators == 0
    assert unit.lko.weight_sum.quantize(D("0.001")) == D("0.679")
    assert unit.lko.sum_below_full  # экран пишет «сумма весов 68%»
    assert unit.lko.score is not None
    assert abs(unit.lko.score - D("3.095")) < D("0.001")
    # Без проверок decimus ЭС нет, и вес на РС не переносится.
    assert unit.es.score is None
    assert unit.es.status == "no_audit"
