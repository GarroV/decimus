"""New content templates keep subject/body together and preserve legacy inspection slots."""

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

from src.db import mailing_templates as store
from src.domain import mailing_content as mc

pytestmark = requires_db


@pytest.fixture
def database(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


@pytest.mark.parametrize("kind", mc.KINDS)
def test_actual_subject_body_version_reset_and_legacy_compatibility(
    database: str, kind: str
) -> None:
    store.save("plan", "en", "Legacy {unit}", actor="admin")
    subject, body = mc.defaults(kind, "en")
    assert store.save("message", "en", body, subject=subject, actor="admin", kind=kind) == 1
    row = store.current(kind)[("message", "en")]
    assert row.subject == subject and row.body == body
    assert store.bodies() == {"en": {"plan": "Legacy {unit}"}}
    assert store.save("message", "en", None, actor="admin", kind=kind) == 2
    assert [v.body for v in store.history("message", "en", kind)] == [None, body]
    assert store.current(kind)[("message", "en")].subject is None
