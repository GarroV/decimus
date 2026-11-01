"""Owner's pause: no new plans, no notifications, read-only administration archive."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.db import action_plans, notifications
from src.db.errors import ActionPlanError
from src.domain.features import action_plans_enabled
from src.domain.permissions import Actor, can
from src.web import actions_screen, administration, home_board


@pytest.fixture(autouse=True)
def paused(monkeypatch):
    monkeypatch.delenv("ACTION_PLANS_ENABLED", raising=False)


def test_actual_default_is_paused():
    assert not action_plans_enabled()


@pytest.mark.parametrize("role", ["superadmin", "admin", "developer"])
def test_no_hq_role_can_request_or_manage_live_plans(role):
    assert not can(Actor("HQ", role), "plan.manage")


def test_partner_cannot_submit_a_plan():
    assert not can(Actor("PARTNER", "admin"), "plan.submit")


def test_auto_request_is_a_noop_before_any_sql():
    cursor = Mock()
    assert action_plans.open_auto_request(cursor, "any", actor="owner", on=date.today()) is None
    cursor.execute.assert_not_called()


def test_direct_manual_request_is_blocked_before_database():
    with pytest.raises(ActionPlanError, match="paused"):
        action_plans.request_plan("any", actor="owner")


def test_old_workflow_can_be_explicitly_exercised_without_changing_default(monkeypatch):
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "1")
    assert action_plans_enabled()
    assert can(Actor("HQ", "admin"), "plan.manage")


def test_no_new_plan_notification_or_recipient_lookup():
    cursor = Mock()
    assert notifications.notify(cursor, ["any"], "plan_requested", "/actions") == 0
    cursor.execute.assert_not_called()


def test_default_actions_tab_is_prescriptions_even_for_an_old_plan_link():
    assert actions_screen.tab_of(None) == "prescriptions"
    assert actions_screen.tab_of("plans") == "prescriptions"


@pytest.mark.parametrize("role", ["admin", "superadmin", "developer", "guest", "osb", "control"])
def test_archive_visibility_is_only_for_hq_administrators(role):
    tabs = {t.key for t in administration.tabs_for(SimpleNamespace(role=role, tenant="HQ"))}
    assert ("plans" in tabs) == (role in {"admin", "superadmin"})


def test_no_plan_stickers_when_paused():
    kinds = home_board.kinds_for(home_board.Who("developer", "HQ"))
    assert home_board.PLANS_REVIEW not in kinds
    assert home_board.PLANS_DUE not in kinds


def test_admin_archive_renders_without_live_actions_or_overdue_banners(monkeypatch):
    from test_web_administration import _стенд

    from src.web import plan_archive

    empty = action_plans.PlanList(rows=(), truncated=False)
    monkeypatch.setattr(plan_archive.action_plans, "list_requests", lambda **_: empty)
    for client in _стенд(monkeypatch, tenant="HQ", role="admin"):
        response = client.get("/administration?tab=plans&lang=en")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Action plans are paused" in html
        assert "New requests and notifications are disabled" in html
        assert "overdue" not in html.lower()
        assert 'action="/actions/requests/' not in html
        old = client.get("/actions?tab=plans&id=old-plan&lang=en")
        assert old.status_code == 303
        assert "/administration?tab=plans" in old.headers["Location"]
        assert "id=old-plan" in old.headers["Location"]


@pytest.mark.parametrize("tenant,role", [("HQ", "control"), ("HQ", "osb"), ("GE", "admin")])
def test_archive_cannot_be_opened_by_a_non_admin(monkeypatch, tenant, role):
    from test_web_administration import _стенд

    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        assert client.get("/administration?tab=plans").status_code in (403, 404)


def test_direct_transition_helpers_are_blocked_before_database():
    from src.db import plan_flow

    ident = "00000000-0000-0000-0000-000000000001"
    calls = (
        lambda: action_plans.set_due(ident, actor="owner", due_on=date.today()),
        lambda: action_plans.review(ident, actor="owner", verdict="accepted", comment=""),
        lambda: plan_flow.accept_plan(ident, actor="owner"),
        lambda: plan_flow.return_plan(ident, actor="owner", comment="review"),
        lambda: plan_flow.confirm_row(ident, ident, actor="owner"),
        lambda: plan_flow.set_count_from(ident, actor="owner", count_from=date.today()),
    )
    for call in calls:
        with pytest.raises(ActionPlanError, match="paused"):
            call()


@pytest.mark.parametrize("name", ["list_action_plans", "get_action_plan"])
@pytest.mark.parametrize("role", ["admin", "superadmin", "developer", "guest", "control", "osb"])
def test_mcp_plan_reads_are_archive_admin_only(name, role):
    from src.mcp import policy
    from src.mcp.catalogue import TOOLS

    spec = next(t for t in TOOLS if t.name == name)
    assert policy.permits_tool(role, "HQ", spec) == (role in {"admin", "superadmin"})
    assert not policy.permits_tool("admin", "PARTNER", spec)
