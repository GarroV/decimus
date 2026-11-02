"""PostgreSQL concurrency: HTTP holds no lock; stale probes cannot turn new keys green."""

from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import health_store, secret_crypto, service_keys  # noqa: E402

pytestmark = requires_db
NAME = "pointer.api_key"


@pytest.fixture
def vault(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setenv("POINTER_API_KEY", "fake-env-fallback")
    monkeypatch.setattr(service_keys, "_cache", {})
    return pg_dsn


@pytest.mark.parametrize("mutation", ["replace", "remove"])
def test_inflight_old_probe_cannot_overwrite_atomic_key_invalidation(
    vault: str,
    mutation: str,
) -> None:
    service_keys.save_many({NAME: "fake-old-key"}, provider="pointer", by="qa")
    checked_at = datetime.now(UTC) - timedelta(minutes=5)
    health_store.record("pointer", "green", "health.reason.ok", checked_at)
    captured, finish_http = Event(), Event()

    def old_provider_request() -> bool:
        snapshot = service_keys.probe_snapshot("pointer")
        assert snapshot.values["api_key"] == "fake-old-key"
        captured.set()
        assert finish_http.wait(5), "controlled provider request timed out"
        return health_store.record_key_if_current(
            "pointer", snapshot.fingerprint, "green", "health.reason.ok", datetime.now(UTC)
        )

    def change() -> None:
        if mutation == "replace":
            service_keys.save_many({NAME: "fake-new-key"}, provider="pointer", by="qa")
        else:
            service_keys.clear_many((NAME,))

    with ThreadPoolExecutor(max_workers=2) as pool:
        probe = pool.submit(old_provider_request)
        try:
            assert captured.wait(3)
            # This MUST complete while simulated HTTP is blocked. Holding the SQL
            # lock during provider I/O would make this bounded future fail.
            pool.submit(change).result(timeout=3)
        finally:
            finish_http.set()
        assert probe.result(timeout=5) is False
    status = health_store.probes()["pointer"]
    assert (status.light, status.reason, status.checked_at) == (
        "grey",
        "health.reason.credentials_recheck",
        checked_at,
    )
    with psycopg.connect(vault) as conn:
        row = conn.execute(
            "select row(h.*)::text from health.checks h where code='pointer'"
        ).fetchone()
    assert "fake-old-key" not in row[0] and "fake-new-key" not in row[0]


def test_result_and_mutation_contending_on_same_service_never_leave_false_green(vault: str) -> None:
    service_keys.save_many({NAME: "fake-old-key"}, provider="pointer", by="qa")
    snapshot = service_keys.probe_snapshot("pointer")
    health_store.record("pointer", "green", "health.reason.ok", datetime.now(UTC))
    with ThreadPoolExecutor(max_workers=2) as pool:
        with psycopg.connect(vault) as held:
            service_keys.probe_snapshot("pointer", conn=held)
            result = pool.submit(
                health_store.record_key_if_current,
                "pointer",
                snapshot.fingerprint,
                "green",
                "health.reason.ok",
                datetime.now(UTC),
            )
            change = pool.submit(
                service_keys.save_many, {NAME: "fake-new-key"}, provider="pointer", by="qa"
            )
        result.result(timeout=5)
        change.result(timeout=5)
    assert health_store.probes()["pointer"].light == "grey"
    assert service_keys.probe_snapshot("pointer").values["api_key"] == "fake-new-key"


def test_probe_lock_is_per_service_not_global(vault: str) -> None:
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(vault) as held:
            service_keys.probe_snapshot("pointer", conn=held)
            # A different service can be configured before the held lock releases.
            changed = pool.submit(
                service_keys.save_many, {"model_key": "fake-model-key"}, provider="openai", by="qa"
            )
            changed.result(timeout=3)


def test_admin_can_invalidate_health_but_cannot_fabricate_checked_at(vault: str) -> None:
    with psycopg.connect(vault) as conn:
        allowed = conn.execute(
            "select has_column_privilege('dodo_audit_admin', 'health.checks', "
            "'light','UPDATE'), has_column_privilege('dodo_audit_admin', "
            "'health.checks','reason','UPDATE'), has_column_privilege("
            "'dodo_audit_admin','health.checks','checked_at','UPDATE')"
        ).fetchone()
    assert allowed == (True, True, False)


def test_stale_old_result_does_not_erase_a_valid_new_version_probe(vault: str) -> None:
    service_keys.save_many({NAME: "fake-old-key"}, provider="pointer", by="qa")
    old = service_keys.probe_snapshot("pointer")
    service_keys.save_many({NAME: "fake-new-key"}, provider="pointer", by="qa")
    new = service_keys.probe_snapshot("pointer")
    checked = datetime.now(UTC)
    assert health_store.record_key_if_current(
        "pointer", new.fingerprint, "green", "health.reason.ok", checked
    )
    assert not health_store.record_key_if_current(
        "pointer", old.fingerprint, "green", "health.reason.ok", datetime.now(UTC)
    )
    status = health_store.probes()["pointer"]
    assert status.light == "green" and status.checked_at == checked
    assert status._key_fingerprint == new.fingerprint


def test_env_version_change_is_unknown_in_both_shared_and_key_display_status(
    vault: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.domain import service_keys as registry
    from src.health import rows
    from src.web.service_keys_screen import _row

    monkeypatch.setenv("POINTER_API_KEY", "fake-env-before-restart")
    old = service_keys.probe_snapshot("pointer")
    checked = datetime.now(UTC)
    assert health_store.record_key_if_current(
        "pointer", old.fingerprint, "green", "health.reason.ok", checked
    )
    monkeypatch.setenv("POINTER_API_KEY", "fake-env-after-restart")
    raw = health_store.probes()
    shared = rows.probe_status("pointer", raw["pointer"], checked, every=None)
    service = registry.service("pointer")
    assert service is not None
    key_display = _row(service, {}, raw).health
    assert shared.light == "grey" and key_display is not None and key_display.light == "grey"
    assert shared.checked_at == checked
    assert old.fingerprint.hex() not in repr(shared)
    assert "fake-env-before-restart" not in repr(shared)


def test_client_id_display_bypasses_resolver_cache_after_another_process_update(vault: str) -> None:
    from src.domain import service_keys as registry
    from src.web.service_keys_screen import _row

    name = "ispring.client_id"
    old, new = "fake-old-client-AAAA", "fake-new-client-BBBB"
    service_keys.save_many(
        {name: old, "ispring.client_secret": "fake-secret"}, provider="ispring", by="qa"
    )
    assert service_keys.resolve("ispring", "client_id") == old
    # Separate connection models an update performed by another process, which
    # cannot clear this process's existing resolver cache.
    with psycopg.connect(vault) as conn:
        conn.execute(
            "update vault.secrets set ciphertext=%s,last4=%s,set_at=now() where name=%s",
            (secret_crypto.encrypt(name, new), new[-4:], name),
        )
    assert service_keys.resolve("ispring", "client_id") == old
    service = registry.service("ispring")
    assert service is not None
    displayed = _row(service, service_keys.statuses(), {})
    field = next(f for f in displayed.fields if f.code == "client_id")
    assert field.identifier == new
    assert field.status is not None and field.status.last4 == new[-4:]
