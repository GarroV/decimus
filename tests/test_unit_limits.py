"""D755: лимит проверок на пиццерию у партнёра на время теста — решение без базы.

Чистая функция решает, нельзя ли заводить шестую проверку; слив и загрузка
спрашивают её через `refuse_over_limit`. Запуск с базой — `test_db_unit_limits.py`.
"""

from __future__ import annotations

import pytest

from src.db import unit_limits
from src.db.errors import HistoryImportError, UnitRefusedError
from src.db.unit_limits import PARTNER_INSPECTIONS_PER_UNIT, limit_reached, refuse_over_limit


def test_лимит_партнёра_пять_проверок_на_пиццерию() -> None:
    assert PARTNER_INSPECTIONS_PER_UNIT == 5


def test_пятая_проверка_партнёра_проходит_шестая_нет() -> None:
    assert not limit_reached("GE", existing=4)
    assert limit_reached("GE", existing=5)
    assert not limit_reached("GE", existing=PARTNER_INSPECTIONS_PER_UNIT - 1)
    assert limit_reached("GE", existing=PARTNER_INSPECTIONS_PER_UNIT)
    assert limit_reached("GE", existing=PARTNER_INSPECTIONS_PER_UNIT + 3)


def test_пространство_ук_без_лимита() -> None:
    assert not limit_reached("HQ", existing=1000)


def test_историческая_загрузка_не_режется_лимитом() -> None:
    assert not limit_reached("GE", existing=1000, origin="legacy")


class _Курсор:
    """Курсор, который отвечает на подсчёт заданным числом и помнит запросы."""

    def __init__(self, сколько: int) -> None:
        self.сколько = сколько
        self.запросы: list[str] = []

    def execute(self, sql: str, params: object = None) -> None:
        self.запросы.append(sql)

    def fetchone(self) -> tuple[int]:
        return (self.сколько,)


def test_отказ_в_шестой_называет_пиццерию_и_говорит_на_двух_языках() -> None:
    курсор = _Курсор(PARTNER_INSPECTIONS_PER_UNIT)

    with pytest.raises(HistoryImportError) as отказ:
        refuse_over_limit(курсор, tenant="GE", unit_id="u1", unit_name="Batumi-1")

    текст = str(отказ.value)
    assert "Для пиццерии «Batumi-1» достигнут лимит тестового периода: 5 проверок" in текст
    assert "Обратитесь к управляющей компании" in текст
    assert "«Batumi-1» has reached the test-period limit of 5 inspections" in текст
    # и бот, и слив ловят его как отказ точки — каждый своим типом
    assert isinstance(отказ.value, UnitRefusedError)


def test_пятая_проходит_без_отказа() -> None:
    refuse_over_limit(
        _Курсор(PARTNER_INSPECTIONS_PER_UNIT - 1), tenant="GE", unit_id="u1", unit_name="Batumi-1"
    )


def test_ук_и_историческая_не_ходят_в_базу() -> None:
    курсор = _Курсор(10_000)

    refuse_over_limit(курсор, tenant="HQ", unit_id="u1", unit_name="Batumi-1")
    refuse_over_limit(курсор, tenant="GE", unit_id="u1", unit_name="Batumi-1", origin="legacy")

    assert курсор.запросы == []


def test_подсчёт_не_берёт_снятые_и_исторические() -> None:
    """Запрос подсчёта держит правила «что считается» — ломать их молча нельзя."""
    sql = unit_limits._COUNT_SQL
    assert "retracted_at is null" in sql
    assert "origin <> 'legacy'" in sql


def test_ранний_отказ_на_старте_ук_и_без_базы_проходит(monkeypatch: pytest.MonkeyPatch) -> None:
    """УК не ходит в базу; у партнёра без базы старт не блокируется (заслон — на вставке)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    unit_limits.refuse_start_over_limit("HQ", "Batumi-1")
    unit_limits.refuse_start_over_limit("GE", "Batumi-1")
