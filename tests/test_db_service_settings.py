"""Actual PostgreSQL persistence, global reads, restricted writes and no backlog burst."""

import os
import subprocess
import sys
from datetime import timedelta

import psycopg
import pytest
from conftest import requires_db
from db_harness import set_retraction_env

from src.db import notifications, service_settings
from src.domain.features import action_plan_state, action_plans_enabled, feature_scope
from src.settings_read import read_boolean

pytestmark = requires_db


@pytest.fixture
def admin(pg_dsn, db_env, monkeypatch):
    set_retraction_env(db_env, monkeypatch)
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "0")
    return pg_dsn


def test_persisted_switch_changes_all_fresh_readers_and_env0_does_not_override(admin):
    assert read_boolean("action_plans_enabled") is None
    assert not action_plans_enabled()
    service_settings.set_action_plans(True, actor="hq-admin")
    fresh = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.domain.features import action_plans_enabled; "
            "print(int(action_plans_enabled()))",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=dict(os.environ),
    )
    assert fresh.stdout.strip() == "1", "independent process observes persisted ON despite env0"
    with feature_scope():
        assert action_plans_enabled()
        first = action_plan_state().saved
        assert first.changed_by == "hq-admin"
    service_settings.set_action_plans(False, actor="hq-superadmin")
    with feature_scope():
        assert not action_plans_enabled()
    service_settings.set_action_plans(True, actor="hq-admin")
    assert read_boolean("action_plans_enabled").notifications_after >= first.notifications_after


def test_application_role_cannot_write_global_setting(admin, db_env):
    service_settings.set_action_plans(False, actor="hq-admin")
    with psycopg.connect(db_env) as conn:
        assert conn.execute("select enabled from service_settings").fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update service_settings set enabled = true")


def test_on_does_not_replay_old_unread_notifications_or_create_plans(admin):
    with psycopg.connect(admin) as conn:
        conn.execute("insert into tenants (code) values ('HQ') on conflict do nothing")
        user = conn.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'settings-test', 'scrypt$synthetic-not-for-login', 'admin') "
            "returning id::text"
        ).fetchone()[0]
        before = conn.execute("select count(*) from action_plan_requests").fetchone()[0]
    service_settings.set_action_plans(True, actor="hq-admin")
    first = read_boolean("action_plans_enabled")
    old = first.notifications_after - timedelta(days=1)
    new = first.notifications_after + timedelta(seconds=1)
    with psycopg.connect(admin) as conn:
        for kind, at in [("plan_requested", old), ("plan_submitted", new), ("rx_requested", old)]:
            conn.execute(
                "insert into notifications(user_id, kind, link, params, created_at) "
                "values (%s, %s, '/actions', '{}'::jsonb, %s)",
                (user, kind, at),
            )
    with feature_scope():
        assert {n.kind for n in notifications.list_for(user)} == {"plan_submitted", "rx_requested"}
        assert notifications.unread_count(user) == 2
    service_settings.set_action_plans(True, actor="hq-admin")
    assert read_boolean("action_plans_enabled").notifications_after == first.notifications_after
    service_settings.set_action_plans(False, actor="hq-admin")
    assert notifications.unread_count(user) == 1
    with psycopg.connect(admin) as conn:
        assert conn.execute("select count(*) from notifications").fetchone()[0] == 3
        assert conn.execute("select count(*) from action_plan_requests").fetchone()[0] == before


def test_real_flask_toggle_persists_and_guards_follow_new_requests(admin, monkeypatch):
    from web_harness import СВОЙ, войти, подменить_двери, собрать

    from src.db import action_plans
    from src.db.errors import ActionPlanError
    from src.domain.permissions import Actor, can

    calls = подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        for value, enabled in [("1", True), ("0", False)]:
            response = client.post(
                "/administration/plans/settings?lang=en",
                data={"enabled": value},
                headers={"Origin": СВОЙ},
            )
            assert response.status_code == 303
            assert "lang=en" in response.headers["Location"]
            page = client.get(response.headers["Location"])
            assert page.status_code == 200
            assert "Action-plan settings" in page.get_data(as_text=True)
            assert read_boolean("action_plans_enabled").enabled is enabled
            assert bool(can(Actor("HQ", "admin"), "plan.manage")) is enabled
            assert bool(can(Actor("RS", "admin"), "plan.submit")) is enabled
        # A paused operation refuses before looking up this nonexistent object.
        with pytest.raises(ActionPlanError, match="paused"):
            action_plans.request_plan("not-a-real-inspection", actor="director")
    changes = [r for r in calls["action_journal"] if r["action"] == "action_plan_setting"]
    assert len(changes) == 2
    assert {r["outcome"] for r in changes} == {"303"}
