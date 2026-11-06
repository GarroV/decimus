"""Номер решения в `docs/furca/decisions.md` встречается один раз (#1407, D717).

Параллельные ветки брали один и тот же «максимум плюс один» и заводили повтор: D492, D542,
D640 (а 06.11.2026 — D715). Вторые записи переименованы в `D492b`, `D542b`, `D640b`; новый
повтор роняет этот тест, а не обнаруживается через месяц по спутанным ссылкам.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

DECISIONS = Path(__file__).resolve().parent.parent / "docs" / "furca" / "decisions.md"
ROW = re.compile(r"^\| (D\d+[a-z]?) \|", re.MULTILINE)


def _ids(text: str) -> list[str]:
    return ROW.findall(text)


def test_номера_решений_не_повторяются() -> None:
    повторы = sorted(
        k for k, n in Counter(_ids(DECISIONS.read_text(encoding="utf-8"))).items() if n > 1
    )
    assert not повторы, (
        f"в decisions.md повторены номера {повторы}: возьмите максимум D### в origin/main "
        "плюс один (после fetch) и перепроверьте перед слиянием"
    )


def test_проверка_видит_повтор() -> None:
    """Прогон на сломанном тексте: без этого зелёный тест мог бы ничего не проверять."""
    сломанный = "| D001 | x |\n| D002 | x |\n| D001 | y |\n"
    assert [k for k, n in Counter(_ids(сломанный)).items() if n > 1] == ["D001"]
