"""D755: лимит проверок на пиццерию у партнёра — на настоящей базе.

Пространство партнёра GE: пять проверок на пиццерию проходят, шестая — отказ
и на сливе из бота, и на черновике загрузки (веб, MCP). УК лимит не касается,
историческая загрузка в счёт не идёт, повторный слив пятой проверки — не отказ.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from db_harness import привязать_страну, слить_проверку, точка_справочника  # noqa: E402

from src.db import imports as db  # noqa: E402
from src.db.errors import InspectionLimitError  # noqa: E402
from src.db.unit_limits import PARTNER_INSPECTIONS_PER_UNIT  # noqa: E402

pytestmark = requires_db

ТОЧКА = "Batumi-1"


@pytest.fixture
def сеть(pg_dsn: str, db_env: str, domain_env: Path) -> None:
    точка_справочника(ТОЧКА, country="GE", city="Batumi")
    привязать_страну(pg_dsn, tenant="GE", country="GE")


def _день(n: int) -> str:
    return f"2026-10-{n:02d}"


def _заполнить(tenant: str, *, сколько: int = PARTNER_INSPECTIONS_PER_UNIT) -> None:
    for n in range(1, сколько + 1):
        слить_проверку(unit=ТОЧКА, tenant=tenant, date=_день(n))


def test_шестая_проверка_партнёра_на_слиянии_отказ(сеть: None) -> None:
    _заполнить("GE")

    with pytest.raises(InspectionLimitError, match="достигнут лимит тестового периода: 5"):
        слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(20))


def test_ук_без_лимита(сеть: None) -> None:
    _заполнить("HQ", сколько=PARTNER_INSPECTIONS_PER_UNIT + 1)


def test_лимит_считается_по_пространству_а_не_по_точке_вообще(сеть: None) -> None:
    _заполнить("HQ")

    слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(20))


def _шапка(день: date, *, origin: str) -> db.NewDraft:
    историческая = origin == "legacy"
    return db.NewDraft(
        tenant="GE",
        unit=ТОЧКА,
        inspection_date=день,
        kind="planned",
        checklist_code="bizdev",
        checklist_version="legacy:x" if историческая else "v1",
        auditor="",
        report_lang="ru",
        speech_lang="ru",
        origin=origin,
        reported_pct=90.0 if историческая else None,
    )


def test_историческая_загрузка_не_в_счёт_и_не_режется(сеть: None) -> None:
    _заполнить("GE")

    for n in (1, 2):
        db.create_draft(_шапка(date(2024, 3, n), origin="legacy"), apply_score=None)

    with pytest.raises(InspectionLimitError):
        слить_проверку(unit=ТОЧКА, tenant="GE", date=_день(20))


def test_черновик_загрузки_партнёра_шестым_отказ(сеть: None) -> None:
    _заполнить("GE")

    with pytest.raises(InspectionLimitError, match="Batumi-1"):
        db.create_draft(_шапка(date(2026, 10, 25), origin="import"), apply_score=lambda _d: None)  # type: ignore[arg-type,return-value]
