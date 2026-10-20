"""Сроки ожидания базы по умолчанию (`src/db/timeouts.py`, F-119)."""

from __future__ import annotations

import pytest
from psycopg.conninfo import conninfo_to_dict

from src.db.timeouts import timed_dsn

URL = "postgresql://app:secret@db:5432/audit"


def test_url_gets_statement_lock_and_connect_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_STATEMENT_TIMEOUT_S", raising=False)
    monkeypatch.delenv("DB_LOCK_TIMEOUT_S", raising=False)
    parts = conninfo_to_dict(timed_dsn(URL))
    assert parts["connect_timeout"] == "10"
    assert parts["options"] == "-c statement_timeout=30000 -c lock_timeout=10000"
    assert parts["host"] == "db"
    assert parts["password"] == "secret"


def test_explicit_options_and_connect_timeout_are_not_overridden() -> None:
    dsn = "host=db dbname=audit connect_timeout=3 options=-cstatement_timeout=600000"
    assert conninfo_to_dict(timed_dsn(dsn)) == conninfo_to_dict(dsn)


def test_env_overrides_and_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_S", "120")
    monkeypatch.setenv("DB_LOCK_TIMEOUT_S", "0")
    assert conninfo_to_dict(timed_dsn(URL))["options"] == "-c statement_timeout=120000"
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_S", "0")
    assert "options" not in conninfo_to_dict(timed_dsn(URL))


def test_bad_env_value_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_S", "abc")
    monkeypatch.delenv("DB_LOCK_TIMEOUT_S", raising=False)
    assert "statement_timeout=30000" in conninfo_to_dict(timed_dsn(URL))["options"]
