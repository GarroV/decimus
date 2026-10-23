"""Срок строки электронного плана — ядро: партнёр читает его как факт (шаг 2 эпика #1168).

Дни строки отдаёт движок (`tests/test_report_plan_terms.py`); здесь только сложение:
срок строки = начало отсчёта + дни, действующий срок = перенос с согласием, иначе более
ранний из срока партнёра и положенного. Срок ответа планом — `plan_due_days` методики.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.domain.errors import ConfigError
from src.domain.plan_due import effective_row_due, plan_due_days, plan_due_on, row_due_on

START = date(2026, 10, 1)


class TestСрокВЭтуДату:
    def test_срок_строки_это_начало_плюс_дни(self) -> None:
        assert row_due_on(START, 5) == date(2026, 10, 6)

    def test_нуль_дней_это_немедленно_сам_день_начала(self) -> None:
        assert row_due_on(START, 0) == START

    def test_отрицательные_дни_это_отказ(self) -> None:
        with pytest.raises(ConfigError):
            row_due_on(START, -1)

    def test_срок_ответа_планом_из_методики(self, domain_env: Path) -> None:
        assert plan_due_on(START) == START + timedelta(days=plan_due_days())


class TestДействующийСрок:
    def test_без_своего_срока_положенный(self) -> None:
        assert effective_row_due(START, 5, None, None) == date(2026, 10, 6)

    def test_партнёр_может_раньше(self) -> None:
        assert effective_row_due(START, 5, date(2026, 10, 3), None) == date(2026, 10, 3)

    def test_позже_положенного_партнёр_не_ставит(self) -> None:
        assert effective_row_due(START, 5, date(2026, 10, 20), None) == date(2026, 10, 6)

    def test_сдвиг_начала_пересчитывает_положенный_срок(self) -> None:
        assert effective_row_due(date(2026, 10, 10), 5, None, None) == date(2026, 10, 15)

    def test_перенос_с_согласием_не_двигается_с_началом(self) -> None:
        перенос = date(2026, 11, 1)
        assert effective_row_due(date(2026, 10, 10), 5, date(2026, 10, 12), перенос) == перенос
