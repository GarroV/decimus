"""Привычная зона пункта в своём пространстве (#1109): по записям прошлых проверок."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db.push import push_inspection  # noqa: E402
from src.db.queries import usual_zone  # noqa: E402
from src.domain import add_finding, start_inspection  # noqa: E402

pytestmark = requires_db

ТЕНАНТ = "default"
НЕДАВНО = (date.today() - timedelta(days=20)).isoformat()


def _проверки(зоны: list[str], *, дата: str = НЕДАВНО, с: int = 1) -> None:
    """По проверке на зону: в одной проверке пункт в зоне записывается один раз."""
    for чат, зона in enumerate(зоны, start=с):
        start_inspection(чат, unit="Белград-1", kind="planned", report_lang="ru", date=дата)
        add_finding(чат, code="PRD06", level="D1", zone=зона, text="нагар")
        push_inspection(чат)


def test_пункт_почти_всегда_в_одной_зоне_даёт_её(domain_env: Path, db_env: str) -> None:
    _проверки(["hot_kitchen", "hot_kitchen", "hot_kitchen"])

    assert usual_zone(tenant=ТЕНАНТ, code="PRD06") == "hot_kitchen"
    assert usual_zone(tenant="другой-арендатор", code="PRD06") is None, "чужое пространство"


def test_мало_записей_или_разброс_привычкой_не_считается(domain_env: Path, db_env: str) -> None:
    _проверки(["hot_kitchen", "hot_kitchen"])
    assert usual_zone(tenant=ТЕНАНТ, code="PRD06") is None

    _проверки(["cold_kitchen", "cold_kitchen"], с=3)
    assert usual_zone(tenant=ТЕНАНТ, code="PRD06") is None


def test_записи_старше_года_не_считаются(domain_env: Path, db_env: str) -> None:
    давно = (date.today() - timedelta(days=400)).isoformat()
    _проверки(["hot_kitchen", "hot_kitchen", "hot_kitchen"], дата=давно)

    assert usual_zone(tenant=ТЕНАНТ, code="PRD06") is None
