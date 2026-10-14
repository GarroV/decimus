"""D490: какое правило дало букву и расшифровка оценки — в движке, не в вебе.

Это ядро: человек читает «90 % D» рядом с «90 % B» как противоречие, и ответ
«потому что такое правило» обязан приходить оттуда же, откуда пришла буква.
Поэтому `compute` берёт букву у `grade_rule`, а расшифровка строится из тех же
записей и потерь зон, что дали итог.

Конфигурация здесь своя, а не боевой `data/scoring.json`: боевая методика лежит
вне git, а проверка правила не должна зависеть от того, есть ли она на машине.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ДВИЖОК = Path(__file__).resolve().parents[1] / "engine" / "audit.py"


def движок() -> Any:
    spec = importlib.util.spec_from_file_location("audit_grade_rule", ДВИЖОК)
    assert spec and spec.loader
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль


def _правило(grade: str, **условие: float) -> dict[str, Any]:
    return {"grade": grade, "if": условие, "label_ru": grade, "label_en": grade}


CFG: dict[str, Any] = {
    "start_pct": 100.0,
    "penalty": {"D1": 0.5, "D2": 2.0},
    "repeat_multiplier": 2.0,
    "d3": {"mode": "zero_zone_share", "skip_other_violations_in_d3_zone": True},
    "deadlines": {"max_days": {"D1": 14, "D2": 10, "D3": 0}},
    "grades": {
        "rules": [
            _правило("D", min_d3=1),
            _правило("C", min_d2=2),
            _правило("C", pct_below=90.0),
            _правило("A", pct_at_least=95.0, max_d2=0),
            _правило("B", pct_at_least=90.0, max_d2=1),
        ],
        "fallback": {"grade": "C", "label_ru": "C", "label_en": "C"},
    },
}

ЗОНЫ = [
    {"code": "hot_kitchen", "name_ru": "Горячий цех", "name_en": "Hot kitchen", "share_pct": 10.0},
    {"code": "dining", "name_ru": "Зал", "name_en": "Dining room", "share_pct": 10.0},
    {"code": "fridge", "name_ru": "Холодильная", "name_en": "Fridge", "share_pct": 10.0},
]


def _counts(d1: int = 0, d2: int = 0, d3: int = 0) -> dict[str, int]:
    return {"D1": d1, "D2": d2, "D3": d3}


@pytest.mark.parametrize(
    ("pct", "counts", "index", "grade"),
    [
        (99.0, _counts(d3=1), 0, "D"),
        (99.0, _counts(d2=2), 1, "C"),
        (85.0, _counts(d2=1), 2, "C"),
        (97.5, _counts(d1=5), 3, "A"),
        (92.0, _counts(d2=1), 4, "B"),
        (92.0, _counts(), 4, "B"),
        (96.0, _counts(d2=1), 4, "B"),
    ],
)
def test_grade_rule_возвращает_сработавшее_правило(
    pct: float, counts: dict[str, int], index: int, grade: str
) -> None:
    i, правило = движок().grade_rule(pct, counts, CFG)
    assert (i, правило["grade"]) == (index, grade)
    assert правило is CFG["grades"]["rules"][index]


def test_grade_rule_запасное_правило_имеет_индекс_минус_один() -> None:
    cfg = {
        **CFG,
        "grades": {"rules": [_правило("A", pct_at_least=95.0)], "fallback": {"grade": "C"}},
    }
    i, правило = движок().grade_rule(80.0, _counts(), cfg)
    assert (i, правило["grade"]) == (-1, "C")


def _оценка(findings: list[dict[str, Any]]) -> dict[str, Any]:
    состояние = {"meta": {"date": "2026-10-14"}, "findings": findings}
    return движок().compute(состояние, [], ЗОНЫ, CFG)


def _find(n: int, level: str, zone: str, repeat: bool = False) -> dict[str, Any]:
    return {"n": n, "qid": f"Q{n:02d}", "level": level, "zone": zone, "repeat": repeat}


def test_compute_берёт_букву_и_правило_у_grade_rule() -> None:
    res = _оценка([_find(1, "D3", "hot_kitchen")])
    assert res["grade"] == "D"
    assert res["grade_rule"] == {"index": 0, "if": {"min_d3": 1}, "better_if": None}


def test_расшифровка_Батуми_сходится_с_итогом() -> None:
    # D1 x10 (две зоны), D2 x2 (одна в зоне с D3), D3 x1: 100 - 5 - 2 - 10 = 83.
    находки = [_find(n, "D1", "dining" if n <= 5 else "fridge") for n in range(1, 11)]
    находки += [
        _find(11, "D2", "fridge"),
        _find(12, "D2", "hot_kitchen"),
        _find(13, "D3", "hot_kitchen"),
    ]
    res = _оценка(находки)
    b = res["breakdown"]
    assert b["exact"] is True
    assert b["skipped"] == {"D2": 1}
    assert b["total"] == res["pct"] == 83.0
    потери = sum(line["loss"] for line in b["lines"])
    assert round(b["start"] - потери, 2) == res["pct"]
    kinds = [(x["kind"], x.get("level"), x["count"], x["loss"]) for x in b["lines"]]
    assert kinds == [("level", "D1", 10, 5.0), ("level", "D2", 1, 2.0), ("d3_zone", None, 1, 10.0)]


def test_расшифровка_показывает_повторы_отдельной_строкой() -> None:
    res = _оценка([_find(1, "D1", "dining", repeat=True), _find(2, "D1", "dining")])
    строки = [(x["level"], x["repeat"], x["count"], x["loss"]) for x in res["breakdown"]["lines"]]
    assert строки == [("D1", False, 1, 0.5), ("D1", True, 1, 1.0)]


def test_расшифровка_не_точна_если_потолок_зоны_обрезал_вычет() -> None:
    cfg = {**CFG, "cap_zone_loss_at_share": True}
    находки = [_find(n, "D2", "dining") for n in range(1, 8)]  # 14 п.п. при доле 10
    res = движок().compute({"meta": {"date": "2026-10-14"}, "findings": находки}, [], ЗОНЫ, cfg)
    assert res["pct"] == 90.0
    assert res["breakdown"]["exact"] is False


def test_у_B_в_ответе_движка_есть_условие_A_для_объяснения_почему_не_выше() -> None:
    res = _оценка([_find(1, "D2", "dining")])
    assert res["grade"] == "B"
    assert res["grade_rule"]["better_if"] == {"pct_at_least": 95.0, "max_d2": 0}
