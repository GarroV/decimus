"""Ячейки таблицы «Качества»: движение к прошлому месяцу и подсветка (D677).

Подсветка — единственное, что отличает «стало хуже» от «так и было»: ошибка здесь прячет
ухудшение или красит нормальное, поэтому пороги и знак движения под тестом.
"""

from __future__ import annotations

from decimal import Decimal as D

from src.web import quality_cells as qc

RKO = qc.Column("rko", "score", 1, threshold=True)
KR = qc.Column("kr", "score", 2)
SHARE = qc.Column("share_agg", "share")
MONEY = qc.Column("rev_dine", "money")


def test_rko_is_tinted_by_ratings_thresholds_regardless_of_movement() -> None:
    assert qc.cell(RKO, D("79.9"), D("70"), None).tone == "bad"  # ниже 80, хотя вырос
    assert qc.cell(RKO, D("85"), D("90"), None).tone == "mid"
    assert qc.cell(RKO, D("90"), D("95"), None).tone == ""  # от 90 — норма, даже упав


def test_other_scores_are_tinted_only_when_worse_than_last_month() -> None:
    assert qc.cell(KR, D("4.50"), D("4.70"), None).tone == "worse"
    assert qc.cell(KR, D("4.70"), D("4.50"), None).tone == ""
    assert qc.cell(KR, D("4.50"), D("4.501"), None).tone == ""  # в пределах точности — без цвета
    assert qc.cell(KR, D("4.50"), None, None).tone == ""  # прошлого месяца нет — нечего сравнивать


def test_shares_have_no_direction_and_are_never_tinted() -> None:
    found = qc.cell(SHARE, D("0.30"), D("0.50"), None)

    assert found.tone == ""
    assert found.text == "30%" and found.delta.text == "-20" and found.delta.kind == "down"


def test_revenue_moves_in_percent_and_is_tinted_when_it_falls() -> None:
    fell = qc.cell(MONEY, D("90000"), D("100000"), "EUR")

    assert fell.text == "90 000 EUR"
    assert fell.delta.text == "-10%" and fell.tone == "worse"
    assert qc.cell(MONEY, D("100"), D("0"), None).delta.text == ""  # деления на ноль нет


def test_missing_value_is_a_dash_not_zero() -> None:
    assert qc.cell(KR, None, D("4.5"), None).text == "—"
    assert qc.cell(SHARE, None, None, None).text == "—"
    assert qc.cell(MONEY, None, None, "EUR").text == "—"


def test_audit_column_only_for_those_who_may_see_it() -> None:
    values = {c.key: D(1) for c in qc.COLUMNS}

    assert len(qc.cells(values, None, None, show_audit=True)) == len(qc.COLUMNS)
    assert len(qc.cells(values, None, None, show_audit=False)) == len(qc.COLUMNS) - 1
