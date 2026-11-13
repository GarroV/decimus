"""Скрипт поиска дублей (#1635): пары находятся по тому же правилу, что при подтверждении."""

from __future__ import annotations

import importlib.util
from datetime import date, datetime
from pathlib import Path

_путь = Path(__file__).resolve().parent.parent / "scripts" / "duplicate_visits.py"
_spec = importlib.util.spec_from_file_location("duplicate_visits", _путь)
assert _spec and _spec.loader
_модуль = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_модуль)

_ЗАПИСИ = [["CLN03", "D1", "hall", "пол"]]
_ПОЗЖЕ = datetime(2026, 11, 3, 10, 8)


def _строка(ident: str, день: date, *, записи=_ЗАПИСИ, pct: str = "97.5", unit: str = "Brasov-1"):
    return (ident, "HQ", unit, день, _ПОЗЖЕ, pct, "A", записи)


def test_пара_с_неделей_разницы_находится() -> None:
    пары = _модуль.find_pairs([_строка("a", date(2026, 10, 27)), _строка("b", date(2026, 11, 3))])

    assert [(x[0], y[0]) for x, y in пары] == [("a", "b")]


def test_другой_набор_или_далёкая_дата_не_пара() -> None:
    строки = [
        _строка("a", date(2026, 10, 1)),
        _строка("b", date(2026, 11, 3)),
        _строка("c", date(2026, 11, 4), записи=[["CLN09", "D1", "hall", "пол"]]),
        _строка("d", date(2026, 11, 4), unit="Other-1"),
    ]

    assert _модуль.find_pairs(строки) == []
