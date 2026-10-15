"""D507: разбивка по процессам — переносится из ответа движка, а не считается.

Базы не нужно: разбор ответа `audit.py score --json` и сверка доливщика —
чистые функции.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.domain.scoring import parse_score

ROOT = Path(__file__).resolve().parents[1]

#: Ответ движка в том виде, как его печатает `score --json`: вклады процессов
#: (7.5 + 2.5) складываются в вычет итога (10.0).
ОТВЕТ: dict[str, Any] = {
    "pct": 90.0,
    "grade": "B",
    "deductions": 10.0,
    "counts": {"D1": 2, "D2": 0, "D3": 0},
    "zones": {},
    "by_process": {
        "CLEAN": {
            "code": "CLEAN", "name_ru": "Чистота", "name_en": "Cleanliness",
            "scored": True, "D1": 1, "D2": 0, "D3": 0, "loss": 7.5,
        },
        "MGMT": {
            "code": "MGMT", "name_ru": "Менеджмент", "name_en": "Management",
            "scored": True, "D1": 1, "D2": 0, "D3": 0, "loss": 2.5,
        },
        "FOOD": {
            "code": "FOOD", "name_ru": "Пищевая безопасность", "name_en": "Food safety",
            "scored": True, "D1": 0, "D2": 0, "D3": 0, "loss": 0.0,
        },
    },
}  # fmt: skip


def _доливщик() -> Any:
    spec = importlib.util.spec_from_file_location(
        "backfill_by_process", ROOT / "tools" / "backfill_by_process.py"
    )
    assert spec is not None and spec.loader is not None
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль


class _Проверка:
    """Только то, что сверка читает у записанной проверки: процент и букву."""

    def __init__(self, pct: float, grade: str) -> None:
        self.inspection = type("Row", (), {"pct": pct, "grade": grade})()


def test_разбивка_по_процессам_доезжает_из_ответа_движка_без_правок() -> None:
    # Act
    оценка = parse_score(ОТВЕТ)

    # Assert — числа те же, что у движка, и вклады сходятся с вычетом.
    assert set(оценка.by_process) == {"CLEAN", "MGMT", "FOOD"}
    assert оценка.by_process["CLEAN"].loss == 7.5
    assert оценка.by_process["CLEAN"].name("en") == "Cleanliness"
    assert оценка.by_process["FOOD"].scored is True
    assert sum(p.loss for p in оценка.by_process.values()) == оценка.deductions


def test_ответ_без_разбивки_даёт_пустую_а_не_выдуманную() -> None:
    assert parse_score({k: v for k, v in ОТВЕТ.items() if k != "by_process"}).by_process == {}


def test_доливщик_пускает_проверку_когда_оценка_и_сумма_сошлись() -> None:
    assert _доливщик().refusal(_Проверка(90.0, "B"), parse_score(ОТВЕТ)) is None


def test_доливщик_отказывает_когда_процент_или_буква_разошлись_с_базой() -> None:
    # Arrange
    ф = _доливщик().refusal

    # Assert — оценку он не переписывает: расхождение называется, а не пишется.
    assert "движок дал 90.0% B" in (ф(_Проверка(91.0, "B"), parse_score(ОТВЕТ)) or "")
    assert ф(_Проверка(90.0, "A"), parse_score(ОТВЕТ)) is not None


def test_доливщик_отказывает_когда_вклады_не_сходятся_с_вычетом() -> None:
    # Arrange
    честная = parse_score(ОТВЕТ)
    сломанная = replace(честная, deductions=честная.deductions + 1.0)

    # Act
    причина = _доливщик().refusal(_Проверка(90.0, "B"), сломанная)

    # Assert
    assert причина is not None and "вклады процессов" in причина


def test_доливщик_отказывает_когда_движок_не_вернул_разбивку() -> None:
    пустая = replace(parse_score(ОТВЕТ), by_process={})
    assert _доливщик().refusal(_Проверка(90.0, "B"), пустая) is not None
