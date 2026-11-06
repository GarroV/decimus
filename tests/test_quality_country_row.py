"""Итог и веса страны считаются по строке страны, а не как среднее итогов пиццерий (D722).

Ядро «Качества»: итог выглядит правдоподобным числом, даже если посчитан не от того. Четыре
строки — из снимка прототипа аналитика (значения страны → веса и итог). У каждой страны две
пиццерии с разбросом вокруг её средних: у них пороги веса РКО разные, поэтому среднее итогов
пиццерий от итога строки страны заметно расходится — тест падает на нём.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP
from decimal import Decimal as D

import pytest

from src.domain import quality as q
from src.web import quality_data as qd


def _unit(
    name: str,
    *,
    rko: str,
    checks: str,
    kr: str,
    maps: str,
    aggs: str | None,
    orders: q.Orders,
) -> qd.UnitHealth:
    overall, weights = qd.overall_values(
        rko=D(rko),
        checks=D(checks),
        kr=D(kr),
        maps=D(maps),
        aggs=None if aggs is None else D(aggs),
        orders=orders,
    )
    values = qd._unit_values(
        rko=D(rko),
        checks=D(checks),
        rs=None,
        audit=None,
        kr=D(kr),
        maps=D(maps),
        aggs=None if aggs is None else D(aggs),
        orders=orders,
        revenue={},
        total=overall.score,
        weights=weights,
    )
    return qd.UnitHealth(name, name, "XX", values, None, (), orders, {}, {}, (), (), "", overall)


def _pair(spread: dict[str, str], mean: dict[str, str | None], orders: q.Orders) -> list:
    """Две пиццерии вокруг средних страны: ± разброс по показателю (в сумме — ровно среднее)."""
    units = []
    for sign in (1, -1):
        shown = {
            k: None if v is None else str(D(v) + sign * D(spread.get(k, "0")))
            for k, v in mean.items()
        }
        units.append(_unit(f"u{sign}", orders=orders, **shown))  # type: ignore[arg-type]
    return units


def _row(mean: dict[str, str | None], spread: dict[str, str], shares: tuple[int, int, int]):
    units = _pair(spread, mean, q.Orders(*shares))
    country = qd._country("XX", units, None, qd.DODOIS_OK)
    # Точка отсчёта: среднее итогов пиццерий — именно оно было до D722.
    units_mean = sum((u.values["total"] or D(0) for u in units), D(0)) / len(units)
    return country, units_mean


def _w(country: qd.CountryHealth) -> tuple[int, int, int, int]:
    v = country.values
    return tuple(  # type: ignore[return-value]
        int((v[k] * 100).to_integral_value(ROUND_HALF_UP))  # type: ignore[operator]
        for k in ("w_rko", "w_kr", "w_maps", "w_aggs")
    )


def _r2(value: D | None) -> D:
    assert value is not None
    return value.quantize(D("0.01"), ROUND_HALF_UP)


# (страна, средние страны, разброс пиццерий, доли заказов %, веса РКО/КР/карты/агрегаторы, итог)
ROWS = [
    (
        "Bulgaria",
        {"rko": "85.04", "checks": "6.52", "kr": "4.71", "maps": "4.40", "aggs": "4.20"},
        {"rko": "3", "checks": "2.6", "kr": "0.2", "maps": "0.1", "aggs": "0.1"},
        (9, 32, 59),
        (50, 23, 20, 7),
        D("4.39"),
    ),
    (
        # В снимке итог 4.40, но по его же весам и значениям выходит 4.37 (проверено вручную:
        # 0.3×4.5445 + 0.2083×4.65 + 0.2×4.21 + 0.2917×4.10); берём расчёт, а не снимок.
        "Poland",
        {"rko": "90.89", "checks": "4.44", "kr": "4.65", "maps": "4.21", "aggs": "4.10"},
        {"rko": "3", "checks": "1.5", "kr": "0.2", "maps": "0.1", "aggs": "0.1"},
        (35, 25, 40),
        (30, 21, 20, 29),
        D("4.37"),
    ),
    (
        "Qatar",
        {"rko": "96.10", "checks": "0", "kr": "4.92", "maps": "4.77", "aggs": "4.90"},
        {"rko": "2", "kr": "0.1", "maps": "0.1", "aggs": "0.1"},
        (71, 23, 6),
        (0, 20, 20, 60),
        D("4.88"),
    ),
    (
        "Serbia",
        {"rko": "88.15", "checks": "4.43", "kr": "4.84", "maps": "4.42", "aggs": None},
        {"rko": "3", "checks": "1", "kr": "0.1", "maps": "0.1"},
        (0, 50, 50),
        (30, 50, 20, 0),
        D("4.63"),
    ),
]


@pytest.mark.parametrize(("name", "mean", "spread", "shares", "weights", "total"), ROWS)
def test_country_weights_and_total_follow_the_country_row(
    name: str,
    mean: dict[str, str | None],
    spread: dict[str, str],
    shares: tuple[int, int, int],
    weights: tuple[int, int, int, int],
    total: D,
) -> None:
    country, mean_of_units = _row(mean, spread, shares)

    assert _w(country) == weights, name
    assert _r2(country.values["total"]) == total, name
    # Строка страны — сами средние, а итог не равен среднему итогов пиццерий.
    assert country.values["rko"] == D(mean["rko"] or 0)
    assert country.overall is not None and country.overall.score == country.values["total"]
    if name != "Qatar":  # без проверок вес РКО у всех нулевой: способы счёта там не различить
        assert _r2(mean_of_units) != total, f"{name}: разброс не различает способы счёта"


def test_country_rko_adj_is_row_rko_over_twenty() -> None:
    country, _ = _row(*ROWS[0][1:4])

    assert country.values["rko_adj"] == D("85.04") / 20
