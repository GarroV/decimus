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
