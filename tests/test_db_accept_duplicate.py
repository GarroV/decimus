"""Подтверждение загруженной проверки, повторяющей принятую с другой датой (#1635).

На настоящей базе: первая проверка принята, вторая — те же записи, дата на неделю
иная — не принимается без `confirm_duplicate`, а с ним принимается.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_DATA, requires_db
from db_harness import set_retraction_env, привязать_страну, точка_справочника
from mcp_checklist_harness import build_edition  # noqa: F401  (держит путь к харнессу)

psycopg = pytest.importorskip("psycopg")

from src.mcp import imports  # noqa: E402
from src.mcp.checklist import Store, current_version  # noqa: E402
from src.mcp.errors import ToolError  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"
КТО = "mcp:tg:4242"


@pytest.fixture
def хранилище(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Store:
    корень = tmp_path / "store"
    monkeypatch.setenv("MCP_CHECKLIST_STORE", str(корень))
    склад = Store(root=корень, live=TEST_DATA)
    current_version(склад)
    return склад


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")
    set_retraction_env(db_env, monkeypatch)


def _проверка(склад: Store, день: str) -> str:
    ответ = imports.import_create_inspection(
        tenant="HQ",
        store=склад,
        actor=КТО,
        mode="current",
        unit=ТОЧКА,
        date=день,
        checklist_code="bizdev",
        auditor="Ivan Petrov",
        reported_pct=98.0,
        reported_grade="B",
    )
    ident = str(ответ["id"])
    imports.import_add_finding(
        tenant="HQ",
        store=склад,
        actor=КТО,
        inspection_id=ident,
        code="CLN03",
        level="D1",
        zone="hot_kitchen",
        text="грязный пол",
    )
    return ident


def _принять(склад: Store, ident: str, день: str, **поля: Any) -> Any:
    return imports.import_accept_inspection(
        tenant="HQ",
        store=склад,
        actor=КТО,
        inspection_id=ident,
        confirm_unit=ТОЧКА,
        confirm_date=день,
        **поля,
    )


def test_повтор_принятой_с_другой_датой_не_принимается(сеть: None, хранилище: Store) -> None:
    первая = _проверка(хранилище, "2026-11-02")
    _принять(хранилище, первая, "2026-11-02")
    вторая = _проверка(хранилище, "2026-11-09")

    with pytest.raises(ToolError, match="повторяет принятую"):
        _принять(хранилище, вторая, "2026-11-09")


def test_с_подтверждением_что_это_другой_визит_принимается(сеть: None, хранилище: Store) -> None:
    первая = _проверка(хранилище, "2026-11-02")
    _принять(хранилище, первая, "2026-11-02")
    вторая = _проверка(хранилище, "2026-11-09")

    ответ = _принять(хранилище, вторая, "2026-11-09", confirm_duplicate=True)

    assert ответ["id"] == вторая


def test_тот_же_набор_далеко_по_дате_не_повтор(сеть: None, хранилище: Store) -> None:
    первая = _проверка(хранилище, "2026-09-01")
    _принять(хранилище, первая, "2026-09-01")
    вторая = _проверка(хранилище, "2026-11-09")

    ответ = _принять(хранилище, вторая, "2026-11-09")

    assert ответ["id"] == вторая


def test_parallel_duplicates_require_explicit_confirmation(
    сеть: None, хранилище: Store, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Второй accept ждёт commit первого, затем видит принятый дубль."""
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from threading import Event
    from time import monotonic, sleep

    from src.db import accept

    first = _проверка(хранилище, "2026-11-02")
    second = _проверка(хранилище, "2026-11-09")
    checked, release = Event(), Event()
    original = accept._refuse_duplicate

    def hold_first(cur: Any, ident: str) -> None:
        original(cur, ident)
        if ident == first:
            checked.set()
            assert release.wait(15), "first acceptance was not released"

    monkeypatch.setattr(accept, "_refuse_duplicate", hold_first)
    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(copy_context().run, _принять, хранилище, first, "2026-11-02")
        try:
            assert checked.wait(10)
            b = executor.submit(copy_context().run, _принять, хранилище, second, "2026-11-09")
            deadline = monotonic() + 5
            waiting = False
            with psycopg.connect(pg_dsn, autocommit=True) as conn:
                while monotonic() < deadline and not b.done():
                    waiting = bool(
                        conn.execute(
                            "select count(*) from pg_stat_activity "
                            "where datname = current_database() and wait_event = 'advisory'"
                        ).fetchone()[0]
                    )
                    if waiting:
                        break
                    sleep(0.02)
            assert waiting, "parallel acceptance bypassed the unit lock"
        finally:
            release.set()
        assert a.result(timeout=15)["id"] == first
        with pytest.raises(ToolError, match="повторяет принятую"):
            b.result(timeout=15)
    with psycopg.connect(pg_dsn) as conn:
        statuses = dict(
            conn.execute(
                "select id::text, status from inspections where id = any(%s::uuid[])",
                ([first, second],),
            ).fetchall()
        )
    assert statuses == {first: "finalized", second: "draft"}
    assert _принять(хранилище, second, "2026-11-09", confirm_duplicate=True)["id"] == second
