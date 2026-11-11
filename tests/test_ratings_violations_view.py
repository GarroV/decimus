"""D746: violation shares and drilldown use the same scoped source rows."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.db.ratings_violations import Occurrence
from src.ratings import violations_view as view
from src.ratings.periods import month_period

PERIOD = month_period(2026, 10)
PREVIOUS = month_period(2026, 9)
U1, U2, U3 = "a" * 32, "b" * 32, "c" * 32
CHECK = "d" * 32
LOADED = datetime(2026, 11, 1, tzinfo=timezone.utc)


def fact(
    *,
    unit=U1,
    country="RS",
    criterion="C1",
    text="Synthetic violation",
    amount=1,
    category="violation",
    checkup=CHECK,
    parent="Synthetic group",
    row=1,
):
    return Occurrence(
        row,
        "rs",
        unit,
        "Synthetic-" + unit[0],
        country,
        text,
        parent,
        category,
        criterion,
        amount,
        checkup,
        None,
        None,
        LOADED,
    )


def test_share_counts_cases_not_pizzerias_and_detail_uses_the_same_scope():
    facts = (
        fact(amount=3),
        fact(unit=U2, amount=2, row=2),
        fact(criterion="C2", text="Other", amount=5, row=3),
        fact(unit=U3, country="TR", amount=99, row=4),
        fact(category="other", amount=88, row=5),
    )
    result = view.assemble("rs", ("RS",), PERIOD, facts)
    assert result.total_cases == 10
    assert result.units == 2
    assert len(result.rows) == 2
    first = next(r for r in result.rows if r.criterion_id == "C1")
    assert (first.cases, first.units, first.share) == (5, 2, 50)
    selected = view.assemble("rs", ("RS",), PERIOD, facts, criterion=first.key).selected
    assert selected is not None
    assert [(u.unit, u.cases) for u in selected.units] == [(U1, 3), (U2, 2)]
    assert all(u.country == "RS" for u in selected.units)
    assert result.photos_available is False and selected.photos_available is False


def test_criterion_id_keeps_translated_text_together_but_not_different_codes():
    result = view.assemble(
        "rs",
        ("RS",),
        PERIOD,
        (
            fact(text="Synthetic original", amount=2),
            fact(text="Synthetic translation", row=2),
            fact(criterion="C2", text="Synthetic original", row=3),
        ),
    )
    assert len(result.rows) == 2
    first = next(r for r in result.rows if r.criterion_id == "C1")
    assert first.cases == 3 and first.identity == "criterion"


def test_legacy_grouping_is_stable_and_not_claimed_to_be_a_criterion_code():
    a = fact(criterion=None, text="  Legacy   wording (AI)")
    b = fact(criterion=None, text="legacy wording", row=2)
    one = view.assemble("rs", ("RS",), PERIOD, (a, b))
    two = view.assemble("rs", ("RS",), PERIOD, (b, a))
    assert len(one.rows) == 1
    assert one.rows[0].key == two.rows[0].key
    assert one.rows[0].identity == "legacy_text"
    assert one.rows[0].criterion_id is None


def test_previous_period_missing_is_unknown_not_zero_and_delta_uses_cases():
    current = (fact(amount=6),)
    missing = view.assemble("rs", ("RS",), PERIOD, current, previous=PREVIOUS)
    assert missing.rows[0].delta is None
    before = (fact(amount=4), fact(criterion="C2", amount=1, row=2))
    known = view.assemble("rs", ("RS",), PERIOD, current, previous=PREVIOUS, before=before)
    assert known.rows[0].previous_cases == 4
    assert known.rows[0].delta == 2
    assert known.rows[0].delta_pct == pytest.approx(50)
    assert known.source == "ratings_exports" and known.loaded_at == LOADED


def test_country_totals_cannot_be_confused_with_network_share():
    result = view.assemble(
        "rs", ("RS", "TR"), PERIOD, (fact(amount=2), fact(country="TR", unit=U2, amount=3, row=2))
    )
    assert [(c.code, c.cases, c.units) for c in result.countries] == [("RS", 2, 1), ("TR", 3, 1)]
    assert result.rows[0].cases == 5 and result.rows[0].units == 2


def test_details_rebuild_safe_checkup_urls_and_never_invent_photos():
    facts = (fact(), fact(checkup=None, row=2))
    base = view.assemble("rs", ("RS",), PERIOD, facts)
    detail = view.assemble("rs", ("RS",), PERIOD, facts, criterion=base.rows[0].key).selected
    assert detail is not None
    unit = detail.units[0]
    assert len(unit.checks) == 1
    assert unit.checks[0].url.startswith("https://knowledgebase.dodois.io/rating#/")
    assert "checkupId=" + CHECK in unit.checks[0].url
    assert unit.rating_url.endswith("/2")
    assert detail.photos_available is False
    assert view.assemble("rs", ("RS",), PERIOD, facts, criterion="unknown").selected is None


def test_empty_scope_does_not_turn_into_network_data():
    result = view.assemble("rs", (), PERIOD, (fact(),))
    assert result.total_cases == 0 and not result.rows and result.loaded_at is None
    with pytest.raises(ValueError):
        view.assemble("other", ("RS",), PERIOD, (fact(),))


def test_metadata_checks_without_violations_do_not_claim_a_clean_result():
    result = view.assemble(
        "rs", ("RS",), PERIOD, (), observed_checkups=3, checkups_loaded_at=LOADED
    )
    assert result.observed_checkups == 3
    assert result.checkups_loaded_at == LOADED
    assert result.coverage == "checks_only" and result.has_data is False
    assert result.loaded_at is None
    assert view.assemble("rs", ("RS",), PERIOD, ()).coverage == "unknown"
    assert view.assemble("rs", ("RS",), PERIOD, (fact(),)).coverage == "violations"
