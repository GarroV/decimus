"""Автозапрос на границе DB: нарушения требуют план, охват/история сохраняются."""

from datetime import date, timedelta
from unittest.mock import MagicMock, Mock

import pytest

from src.db import action_plans
from src.db.accept import _open_plan_request
from src.db.errors import AcceptError, ActionPlanError

ON = date(2026, 10, 30)


@pytest.mark.parametrize(
    ("counts", "needed"),
    [
        ({"D1": 1}, True),
        ({"D2": 1}, True),
        ({"D3": 1}, True),
        ({"D1": 26, "D2": 0, "D3": 0}, True),
        ({"D0": 5, "R": 1, "info": 3}, False),
        ({"D1": 0, "D2": 0, "D3": 0}, False),
        ({}, False),
    ],
)
def test_auto_request_respects_engine_counts_and_reads_terms_only_when_needed(
    monkeypatch: pytest.MonkeyPatch, counts: dict[str, int], needed: bool
) -> None:
    cursor = Mock()
    cursor.fetchone.configure_mock(return_value=("HQ", "finalized", None, counts, "GE", "field"))
    create = Mock(return_value="new-request")
    due = Mock(return_value=ON + timedelta(days=8))
    terms = Mock()
    monkeypatch.setattr(action_plans, "_create_request", create)
    monkeypatch.setattr(action_plans, "plan_due_on", due)

    result = action_plans.open_auto_request(
        cursor, "inspection", actor="reviewer", on=ON, terms=terms
    )

    if needed:
        assert result == "new-request"
        due.assert_called_once_with(ON)
        create.assert_called_once_with(
            cursor,
            "inspection",
            origin="auto",
            actor="reviewer",
            count_from=ON,
            due_on=ON + timedelta(days=8),
            terms=terms,
        )
    else:
        assert result is None
        create.assert_not_called()
        due.assert_not_called()


@pytest.mark.parametrize(
    ("tenant", "origin", "country"),
    [("GE", "field", "GE"), ("HQ", "import", "GE"), ("HQ", "legacy", "GE"), ("HQ", "field", "")],
)
def test_d1_does_not_bypass_space_origin_or_missing_country(
    monkeypatch: pytest.MonkeyPatch, tenant: str, origin: str, country: str
) -> None:
    cursor = Mock()
    cursor.fetchone.configure_mock(
        return_value=(tenant, "finalized", None, {"D1": 1}, country, origin)
    )
    create = Mock()
    due = Mock()
    monkeypatch.setattr(action_plans, "_create_request", create)
    monkeypatch.setattr(action_plans, "plan_due_on", due)

    assert action_plans.open_auto_request(cursor, "inspection", actor="reviewer", on=ON) is None
    create.assert_not_called()
    due.assert_not_called()


def test_existing_auto_request_stays_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    cursor = Mock()
    cursor.fetchone.configure_mock(return_value=("HQ", "finalized", None, {"D1": 1}, "GE", "field"))
    create = Mock(return_value=None)
    monkeypatch.setattr(action_plans, "_create_request", create)
    monkeypatch.setattr(action_plans, "plan_due_on", lambda day: day + timedelta(days=8))

    assert action_plans.open_auto_request(cursor, "inspection", actor="reviewer", on=ON) is None
    create.assert_called_once()


def test_failed_plan_request_is_acceptance_failure_with_d1_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = Mock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.configure_mock(return_value=cursor)
    monkeypatch.setattr(
        "src.db.accept.open_auto_request", Mock(side_effect=ActionPlanError("detail"))
    )

    with pytest.raises(AcceptError, match="D1, D2 или D3") as failed:
        _open_plan_request(connection, "inspection", "reviewer", None)
    assert failed.value.code == "accept_plan_failed"
    assert "detail" not in str(failed.value)
