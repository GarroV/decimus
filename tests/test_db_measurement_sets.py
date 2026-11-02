"""Structured evidence survives push; app and history roles cannot rewrite it."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from conftest import requires_db
from db_harness import accept_pushed, admin_role_dsn
from test_db_reading import сеть  # noqa: F401

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.db.queries import get_inspection  # noqa: E402
from src.db.reach import own_reach  # noqa: E402
from src.domain import add_finding, get_state, start_inspection  # noqa: E402
from src.domain.measurement_sets import save_set  # noqa: E402
from src.domain.revisions import finding_revision  # noqa: E402

pytestmark = requires_db


def test_push_roundtrip_reach_and_finalized_role_protection(сеть, db_env):
    chat = 991111
    start_inspection(chat, unit="Batumi-1", kind="planned", report_lang="ru", tenant="HQ")
    source = add_finding(chat, "INF10", "D0", "hot_kitchen", "Product measurement", reading_c=2)
    value = dict(
        schema=1,
        id="a" * 32,
        revision=None,
        code="CLN05",
        zone="hot_kitchen",
        line_label="Explicit line",
        confirmed=True,
        products=[
            dict(
                id="b" * 32,
                label="Explicit product",
                facts="",
                confirmed_product=True,
                sources=[dict(n=source.n, revision=finding_revision(source))],
            )
        ],
    )
    save_set(chat, value, run_id=get_state(chat).run_id)
    expected = get_state(chat).measurement_sets
    ident = push_inspection(chat)
    detail = get_inspection(ident, reach=own_reach("HQ"), include_on_review=True)
    assert detail is not None and detail.inspection.measurement_sets == expected
    assert get_inspection(ident, reach=own_reach("partner"), include_on_review=True) is None
    accept_pushed(ident)
    for dsn in (db_env, admin_role_dsn(db_env)):
        with psycopg.connect(dsn) as conn:
            conn.execute("select set_config('decimus.space', 'HQ', true)")
            try:
                result = conn.execute(
                    "update inspections set measurement_sets = '{}'::jsonb where id = %s", (ident,)
                )
                assert result.rowcount == 0
            except psycopg.errors.InsufficientPrivilege:
                conn.rollback()
    accepted = get_inspection(ident, reach=own_reach("HQ"))
    assert accepted is not None and accepted.inspection.measurement_sets == expected
