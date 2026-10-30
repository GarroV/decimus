"""Ядро экшн-планов без базы: когда запрос появляется сам, когда он просрочен (D272, D274).

Ошибка здесь тихая и дорогая: лишний запрос партнёру по проверке без D1/D2/D3 или
пропущенный по проверке с нарушением, «просрочено» у плана, который партнёр уже
прислал. Поэтому правила — чистыми функциями и с тестами до кода.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.db.action_plans import (
    STATE_ACCEPTED,
    STATE_ON_REVIEW,
    STATE_REQUESTED,
    STATE_RETURNED,
    due_date,
    is_overdue,
    needs_action_plan,
    plan_state,
)
from src.db.config import load_action_plan_settings
from src.db.errors import ActionPlanError, ConfigError

СРОК = date(2026, 10, 11)


@pytest.mark.parametrize(
    ("counts", "нужен"),
    [
        ({"D1": 5}, True),
        ({}, False),
        ({"D0": 3, "D1": 1}, True),
        ({"D1": 2, "D2": 0, "D3": 0}, True),
        ({"D0": 3, "R": 2, "info": 5}, False),
        ({"D1": 0, "D2": 0, "D3": 0, "D0": 1}, False),
        ({"D2": 1}, True),
        ({"D3": 1}, True),
        ({"D1": 4, "D2": 2, "D3": 1}, True),
    ],
)
def test_запрос_появляется_сам_при_любом_нарушении(counts: dict[str, int], нужен: bool) -> None:
    # Act / Assert — счётчики движка как есть, классы не пересчитываются.
    assert needs_action_plan(counts) is нужен


@pytest.mark.parametrize("level", ["D1", "D2", "D3"])
def test_счётчик_не_числом_это_отказ_а_не_догадка(level: str) -> None:
    with pytest.raises(ActionPlanError):
        needs_action_plan({level: "много"})


@pytest.mark.parametrize(
    ("статус", "сегодня", "просрочен"),
    [
        ("requested", date(2026, 10, 12), True),
        ("requested", СРОК, False),
        ("requested", date(2026, 10, 1), False),
        ("on_review", date(2026, 10, 20), False),
        ("accepted", date(2026, 10, 20), False),
    ],
)
def test_просрочен_только_запрошенный_после_срока(
    статус: str, сегодня: date, просрочен: bool
) -> None:
    """Возвращённый без новой версии — тот же `requested`, он тоже просрочивается."""
    assert is_overdue(статус, СРОК, today=сегодня) is просрочен


def test_неизвестный_статус_не_выдаётся_за_непросроченный() -> None:
    with pytest.raises(ActionPlanError):
        is_overdue("lost", СРОК, today=СРОК)


@pytest.mark.parametrize(
    ("статус", "вердикт", "состояние"),
    [
        ("requested", None, STATE_REQUESTED),
        ("requested", "returned", STATE_RETURNED),
        ("on_review", None, STATE_ON_REVIEW),
        ("accepted", "accepted", STATE_ACCEPTED),
    ],
)
def test_состояние_для_экрана(статус: str, вердикт: str | None, состояние: str) -> None:
    assert plan_state(статус, вердикт) == состояние


def test_срок_считается_от_даты_подтверждения() -> None:
    assert due_date(date(2026, 10, 4), 7) == СРОК


def test_срок_меньше_дня_это_отказ() -> None:
    with pytest.raises(ActionPlanError):
        due_date(date(2026, 10, 4), 0)


def test_предел_файла_по_умолчанию_25_мб() -> None:
    assert load_action_plan_settings({}).max_bytes == 25 * 1024 * 1024


def test_предел_файла_правится_окружением() -> None:
    assert load_action_plan_settings({"ATTACHMENT_MAX_MB": "40"}).max_bytes == 40 * 1024 * 1024


@pytest.mark.parametrize(
    "env",
    [
        {"ATTACHMENT_MAX_MB": "-1"},
        {"ATTACHMENT_MAX_MB": "100000"},
    ],
)
def test_непригодная_настройка_это_отказ_на_старте(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_action_plan_settings(env)
