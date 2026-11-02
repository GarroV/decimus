"""Manual switch overrides env, fails closed and never leaks across operations."""

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from src import settings_read
from src.domain import features
from src.domain.permissions import Actor, can


def setting(enabled=True):
    return settings_read.BooleanSetting(enabled, datetime.now(UTC), "admin", datetime.now(UTC))


@pytest.mark.parametrize(
    ("env", "saved", "expected"),
    [
        ("0", True, True),
        ("1", False, False),
        ("0", None, False),
        ("1", None, True),
        ("garbage", None, False),
    ],
)
def test_persisted_choice_wins_over_env(monkeypatch, env, saved, expected):
    monkeypatch.setenv("ACTION_PLANS_ENABLED", env)
    monkeypatch.setattr(
        features, "read_boolean", lambda key: None if saved is None else setting(saved)
    )
    assert features.action_plans_enabled() is expected


def test_failure_fails_closed_even_with_env_on(monkeypatch):
    monkeypatch.setenv("ACTION_PLANS_ENABLED", "1")

    def broken(key):
        raise settings_read.SettingsUnavailable("unavailable")

    monkeypatch.setattr(features, "read_boolean", broken)
    assert not features.action_plans_enabled()
    assert not features.action_plan_state().known


def test_operation_snapshot_is_bounded_and_next_operation_sees_changes(monkeypatch):
    values = [setting(False), setting(True)]
    reads = []

    def load(key):
        reads.append(key)
        return values.pop(0)

    monkeypatch.setattr(features, "read_boolean", load)
    with features.feature_scope():
        for _ in range(20):
            assert not features.action_plans_enabled()
            assert not can(Actor("HQ", "admin"), "plan.manage")
            assert can(Actor("HQ", "admin"), "service.settings")
    assert len(reads) == 1
    with features.feature_scope():
        assert features.action_plans_enabled()
        assert can(Actor("HQ", "admin"), "plan.manage")
        assert can(Actor("PARTNER", "admin"), "plan.submit")
    assert len(reads) == 2


def test_failed_read_is_bounded_per_operation(monkeypatch):
    reads = []

    def broken(key):
        reads.append(key)
        raise settings_read.SettingsUnavailable("unavailable")

    monkeypatch.setattr(features, "read_boolean", broken)
    with features.feature_scope():
        for _ in range(30):
            assert not features.action_plans_enabled()
    assert len(reads) == 1
    with features.feature_scope():
        assert not features.action_plans_enabled()
    assert len(reads) == 2


def test_adapter_absent_database_allows_fallback_without_connect(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("unexpected connect")

    monkeypatch.setattr(settings_read.psycopg, "connect", forbidden)
    assert settings_read.read_boolean("action_plans_enabled") is None


def test_adapter_does_not_return_env_on_after_database_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic")

    def failed(*args, **kwargs):
        assert kwargs["connect_timeout"] == 3
        assert "statement_timeout=1000" in kwargs["options"]
        raise settings_read.psycopg.OperationalError("private DSN must not escape")

    monkeypatch.setattr(settings_read.psycopg, "connect", failed)
    with pytest.raises(settings_read.SettingsUnavailable, match=r"^OperationalError$"):
        settings_read.read_boolean("action_plans_enabled")


def test_notification_list_and_count_share_snapshot_and_cutoff(monkeypatch):
    from src.db import notifications

    saved = setting()
    reads, statements = [], []

    def load(key):
        reads.append(key)
        return saved

    monkeypatch.setattr(features, "read_boolean", load)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, sql, params):
            statements.append((sql, params))

        def fetchall(self):
            return []

        def fetchone(self):
            return (0,)

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def connected(reason):
        yield Connection()

    monkeypatch.setattr(notifications, "_connected", connected)
    with features.feature_scope():
        user = "00000000-0000-0000-0000-000000000001"
        assert notifications.list_for(user) == []
        assert notifications.unread_count(user) == 0
    assert len(reads) == 1
    assert statements[0][1]["plans_after"] == saved.notifications_after
    assert statements[1][1][2:] == (saved.notifications_after, saved.notifications_after)
