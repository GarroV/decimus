"""Показание термометра хранится рядом с записью (#836).

Тот же приём, что у слов аудитора (T183) и источника записи (D044): свой ключ
`readings` в блоке `domain` файла проверки, а не поле внутри структуры движка.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain import add_finding, drop_finding, get_state, set_reading, start_inspection
from src.domain.config import check_environment
from src.domain.engine import state_file
from src.domain.errors import DomainError, ValidationError
from src.domain.state import read_readings

CHAT = 793_000_836


def _начатая() -> None:
    start_inspection(
        CHAT,
        unit="Проверка показаний",
        kind="planned",
        report_lang="ru",
        date="2026-10-14",
        auditor="Тест",
    )


def _файл() -> Path:
    return state_file(CHAT, check_environment())


def _показание(n: int = 1) -> float | None:
    state = get_state(CHAT)
    assert state is not None
    finding = state.finding(n)
    assert finding is not None
    return finding.reading_c


def test_показание_ложится_с_записью(domain_env: Path) -> None:
    _начатая()

    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар", reading_c=6.5)

    assert _показание() == 6.5


def test_записи_без_замера_показания_нет(domain_env: Path) -> None:
    _начатая()

    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар")

    assert _показание() is None


def test_показание_правится_и_снимается(domain_env: Path) -> None:
    _начатая()
    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар", reading_c=26.0)

    set_reading(CHAT, 1, 6.0)
    assert _показание() == 6.0, "исправленное число не легло"

    set_reading(CHAT, 1, None)
    assert _показание() is None


def test_удаление_записи_уносит_показание(domain_env: Path) -> None:
    _начатая()
    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар", reading_c=6.0)
    assert json.loads(_файл().read_text(encoding="utf-8"))["domain"]["readings"] == {"1": 6.0}

    drop_finding(CHAT, 1)

    assert json.loads(_файл().read_text(encoding="utf-8"))["domain"]["readings"] == {}


@pytest.mark.parametrize("мусор", [1000.0, -100.0, float("nan"), float("inf")])
def test_запредельное_показание_отказывается(domain_env: Path, мусор: float) -> None:
    _начатая()

    with pytest.raises(ValidationError):
        add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар", reading_c=мусор)
    _начатая()
    add_finding(CHAT, "CLN05", "D1", "hot_kitchen", "Нагар")
    with pytest.raises(ValidationError):
        set_reading(CHAT, 1, мусор)


def test_показание_несуществующей_записи_отказ(domain_env: Path) -> None:
    _начатая()

    with pytest.raises(ValidationError):
        set_reading(CHAT, 99, 6.0)


def test_чужая_структура_показаний_читается_отказом(domain_env: Path) -> None:
    raw = {"domain": {"readings": {"1": "шесть"}}}

    with pytest.raises(DomainError):
        read_readings(raw, Path("inspection.json"))
