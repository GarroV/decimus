"""Последние оценки проверок пиццерии для «Стабильно ниже порога» (D658).

Молчащая ошибка здесь: чужая, снятая или ждущая приёмки проверка в окне из двух —
плитка скажет «пиццерия стабильно ниже порога» по оценке, которой не было.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env, слить_проверку, точка_справочника

pytest.importorskip("psycopg")

from src.db.reach import own_reach
from src.db.retract import retract_inspection
from src.db.unit_profiles import set_unit_codes
from src.db.unit_scores import recent_pcts

pytestmark = requires_db

КОД = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


def _точка(name: str, code: str) -> None:
    set_unit_codes([(точка_справочника(name, country="RS"), code)])


def _pcts(**kw: object) -> tuple[float, ...]:
    found = recent_pcts(reach=own_reach("HQ"), countries=("RS",), n=2, **kw)  # type: ignore[arg-type]
    return next((u.pcts for u in found if u.code == КОД), ())


def test_берутся_две_последние_принятые_до_даты_и_без_снятых(
    domain_env: Path, db_env: str, admin_env: str
) -> None:
    # Arrange
    _точка("Белград-1", КОД)
    слить_проверку(unit="Белград-1", tenant="HQ", date="2026-09-01")
    вторая = слить_проверку(unit="Белград-1", tenant="HQ", date="2026-09-15")
    слить_проверку(unit="Белград-1", tenant="HQ", date="2026-10-01")
    слить_проверку(unit="Белград-1", tenant="HQ", date="2026-10-10", accept=False)

    # Act / Assert — ждущая приёмки в счёт не идёт: окно из двух последних принятых.
    assert len(_pcts(until=None)) == 2
    assert len(_pcts(until=date(2026, 9, 20))) == 2
    assert len(_pcts(until=date(2026, 9, 10))) == 1  # до даты была одна

    # Снятая проверка выпадает, окно добирает более старую.
    retract_inspection(вторая, tenant="HQ", reason="дубль")
    assert len(_pcts(until=None)) == 2
    assert len(_pcts(until=date(2026, 9, 20))) == 1


def test_точка_без_кода_и_чужая_страна_не_попадают(
    domain_env: Path, db_env: str, admin_env: str
) -> None:
    точка_справочника("Нови-Сад-1", country="RS")
    слить_проверку(unit="Нови-Сад-1", tenant="HQ", date="2026-09-01")
    слить_проверку(unit="Нови-Сад-1", tenant="HQ", date="2026-09-02")

    assert recent_pcts(reach=own_reach("HQ"), countries=("RS",), until=None, n=2) == ()
    assert _pcts(until=None) == ()
