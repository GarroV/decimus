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


def test_revenue_in_a_month_in_progress_has_no_movement_and_no_tint() -> None:
    open_month = qc.cell(MONEY, D("40000"), D("100000"), "EUR", in_progress=True)

    assert open_month.text == "40 000 EUR"
    assert open_month.delta.kind == "" and open_month.tone == ""
    # Остальные показатели идущего месяца сравниваются как обычно.
    assert qc.cell(KR, D("4.50"), D("4.70"), None, in_progress=True).tone == "worse"


def test_groups_mark_first_column_of_each_group() -> None:
    values = {c.key: D(1) for c in qc.COLUMNS}
    edges = [c.edge for c in qc.cells(values, None, None, show_audit=True)]

    assert [k for k, e in zip((c.key for c in qc.COLUMNS), edges, strict=True) if e] == [
        "rko",
        "rs",
        "kr",
        "maps",
        "aggs",
        "total",
        "share_agg",
        "rev_dine",
        "audit",
    ]


def test_total_moves_like_a_score_and_is_tinted_when_worse() -> None:
    total = qc.Column("total", "score", 2)
    worse = qc.cell(total, D("4.40"), D("4.52"), None)

    assert (worse.text, worse.delta.text, worse.tone) == ("4.40", "-0.12", "worse")
    assert qc.cell(total, D("4.60"), D("4.52"), None).tone == ""


def test_weight_is_whole_percent_without_movement_and_tint() -> None:
    weight = qc.Column("w_kr", "weight")
    c = qc.cell(weight, D("0.2333"), D("0.5"), None)

    assert (c.text, c.delta.kind, c.tone) == ("23%", "", "")
    assert qc.cell(weight, D(0), None, None).text == "0%"  # вес ноль — «0%», не прочерк
    assert qc.cell(weight, None, None, None).text == qc.DASH  # итога нет вообще


def test_network_columns_follow_the_analyst_prototype_order() -> None:
    keys = [c.key for c in qc.shown(show_audit=True, country=False)]

    assert keys == [
        "rko",
        "rko_adj",
        "checks",
        "w_rko",
        "kr",
        "w_kr",
        "maps",
        "w_maps",
        "aggs",
        "w_aggs",
        "total",
        "share_agg",
        "share_app",
        "share_other",
    ]  # без РС, выручки и проверки; оценка рядом со своим весом


def test_country_page_keeps_rs_revenue_and_audit() -> None:
    keys = [c.key for c in qc.shown(show_audit=True)]

    assert {"rs", "rev_dine", "rev_delivery", "audit"} <= set(keys)
    assert "audit" not in [c.key for c in qc.shown(show_audit=False)]


def _total_cell(values: dict) -> qc.Cell:
    shown = qc.shown(False)
    row = qc.cells(values, None, None, show_audit=False)
    return next(c for col, c in zip(shown, row, strict=True) if col.key == "total")


def test_incomplete_total_shows_sum_of_weights_without_tint() -> None:
    values = {"total": D("4.50"), "w_sum": D("0.6793")}
    total_cell = _total_cell(values)
    assert (total_cell.text, total_cell.incomplete, total_cell.tone) == ("4.50", "68%", "")

    assert _total_cell({"total": D("4.50"), "w_sum": D(1)}).incomplete == ""
    # Без суммы весов пометки нет.
    assert _total_cell({"total": D("4.50")}).incomplete == ""
