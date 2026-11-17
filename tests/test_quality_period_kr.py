"""The period row and its review-count breakdown must describe the same KR."""

from dataclasses import replace
from decimal import Decimal as D

from src.db.dodois_metrics import UnitKr
from src.domain.quality import Orders
from src.web.quality_data import UnitHealth, _fold_unit


def month(score: str | None, count: int, *, total: str = "50") -> UnitHealth:
    return UnitHealth(
        "synthetic-unit",
        "Synthetic pizzeria",
        "RS",
        {"kr": D(score) if score is not None and count else None, "total": D(total)},
        UnitKr("synthetic-unit", D(score) if score is not None else None, count, None, 0),
        (),
        Orders(0, 0, 0),
        {},
        {},
        (),
    )


def test_period_kr_uses_review_counts_without_recomputing_monthly_overall():
    folded = _fold_unit([month("1", 1, total="20"), month("5", 99, total="80")])
    assert folded.values["kr"] == D("4.96")
    assert folded.kr_parts is not None
    assert folded.kr_parts.dine_in_avg == D("4.96")
    assert folded.kr_parts.dine_in_count == 100
    assert folded.values["total"] == D("50")


def test_period_kr_ignores_unrated_months_and_counts_both_channels():
    earlier = replace(
        month("1", 1),
        kr_parts=UnitKr("synthetic-unit", D("1"), 1, D("5"), 3),
        values={"kr": D("4"), "total": D("50")},
    )
    folded = _fold_unit([earlier, month("5", 0), month("5", 6)])
    assert folded.values["kr"] == D("4.6")
    assert folded.kr_parts is not None
    assert folded.kr_parts.dine_in_count == 7
    assert folded.kr_parts.delivery_count == 3
