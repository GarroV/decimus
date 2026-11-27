"""Partner release: concurrent writes and preservation of scheduled deletion."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, sleep

import psycopg
import pytest
from conftest import requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника

from src.db import imports, space_freeze, space_limits
from src.db.errors import AccessError, InspectionLimitError
from src.db.web_access import create_account
from src.domain.models import LangTexts, Score

pytestmark = requires_db


def test_freeze_serializes_account_creation_and_preserves_deleted_users(
    pg_dsn: str,
    db_env: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    admin_dsn = set_retraction_env(db_env, monkeypatch)
    person = create_account(
        "release-person",
        tenant="GE",
        password="test-release-password",
        role="auditor",
        email="release@example.test",
    )
    with psycopg.connect(pg_dsn) as owner:
        owner.execute(
            "update web_users set display_name_latin = %s where id = %s",
            ("Release Person", person.id),
        )
    with psycopg.connect(admin_dsn) as freezing:
        freezing.execute("select freeze_space('GE', null)")
        started = Event()

        def create() -> None:
            started.set()
            create_account(
                "release-race", tenant="GE", password="test-release-password", role="auditor"
            )

        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(create)
            assert started.wait(3)
            deadline = monotonic() + 5
            blocked = False
            with psycopg.connect(pg_dsn, autocommit=True) as observer:
                while monotonic() < deadline and not pending.done():
                    blocked = bool(
                        observer.execute(
                            "select exists (select 1 from pg_stat_activity "
                            "where datname = current_database() and wait_event_type = 'Lock' "
                            "and query like '%insert into web_users%')"
                        ).fetchone()[0]
                    )
                    if blocked:
                        break
                    sleep(0.01)
            freezing.commit()
            assert blocked, "Account insertion did not wait for the space transaction"
            with pytest.raises(AccessError):
                pending.result(timeout=15)
    with psycopg.connect(pg_dsn) as conn:
        conn.execute(
            "update web_users set delete_after = now() + interval '30 days' where id = %s",
            (person.id,),
        )
    assert space_freeze.unfreeze_space("GE") == 0
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute(
            "select id, disabled_at is not null, delete_after is not null, "
            "email, display_name_latin "
            "from web_users where id = %s",
            (person.id,),
        ).fetchone()
        assert (
            row is not None
            and str(row[0]) == person.id
            and row[1:] == (True, True, "release@example.test", "Release Person")
        )


def test_concurrent_imports_share_one_remaining_slot(
    pg_dsn: str,
    db_env: str,
    domain_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    точка_справочника("Batumi-1", country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    space_limits.set_limits("GE", inspections_per_unit=1, monthly_spend_usd=None, by="release-test")
    ready = Barrier(2)

    def create(day: int) -> str:
        draft = imports.NewDraft(
            tenant="GE",
            unit="Batumi-1",
            inspection_date=date(2026, 11, day),
            kind="planned",
            checklist_code="bizdev",
            checklist_version="v1",
            auditor="",
            report_lang="ru",
            speech_lang="ru",
            origin="import",
        )
        ready.wait(timeout=5)
        try:
            imports.create_draft(
                draft, apply_score=lambda _d: Score(100.0, "A", LangTexts({}), {}, 0.0, {})
            )
        except InspectionLimitError:
            return "limited"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(create, (1, 2)))
    assert sorted(results) == ["created", "limited"]


def test_spend_summary_cannot_read_foreign_tenant(pg_dsn: str, db_env: str) -> None:
    from conftest import app_role_dsn

    привязать_страну(pg_dsn, tenant="GE", country="GE")
    привязать_страну(pg_dsn, tenant="AM", country="AM")
    with psycopg.connect(pg_dsn) as owner:
        owner.execute(
            "insert into model_usage (kind, model, ok, tenant_code, input_tokens) "
            "values ('recognize', 'test-model', true, 'GE', 42), "
            "('recognize', 'test-model', true, 'AM', 99)"
        )
    with psycopg.connect(app_role_dsn(pg_dsn, space="GE")) as partner:
        assert partner.execute(
            "select input_tokens from model_usage_spend('GE', now() - interval '1 hour')"
        ).fetchone() == (42,)
        assert (
            partner.execute(
                "select * from model_usage_spend('AM', now() - interval '1 hour')"
            ).fetchall()
            == []
        )
