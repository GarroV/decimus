-- Vault mutations invalidate health in the SAME managing transaction/connection.
-- The real probe timestamp is preserved; admin cannot fabricate a fresh probe.
grant update (light, reason) on health.checks to dodo_audit_admin;

-- Private credential version for this result, never returned by web/API contexts.
-- Legacy rows remain unknown until a versioned probe verifies current credentials.
alter table health.checks add column key_fingerprint bytea;
