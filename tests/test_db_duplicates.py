"""Та же проверка с другой датой не должна считаться дважды (#1635) — ядро аналитики.

Дубль в базе удваивает точку в буквах и числе нарушений сети, поэтому правило
«что считать повтором» проверяется без базы, на подменённом курсоре: пустая
проверка и проверка с иным текстом дублем не считаются, одинаковый набор в другом
порядке — считается. Проход подтверждения на настоящей базе — `test_db_accept_duplicate.py`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from src.db.duplicates import find_duplicate, same_findings, signature

_СВОЙ = "own"
_ЧУЖОЙ = "other"


class _Курсор:
    """Отдаёт записи по идентификатору проверки и кандидатов — как ответила бы база."""

    def __init__(self, записи: dict[str, list[tuple[str, str, str, str]]], кандидаты: list[Any]):
        self._записи = записи
        self._кандидаты = кандидаты
        self._ответ: list[Any] = []

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        if "from findings" in sql:
            self._ответ = self._записи[params["id"]]
        else:
            self._ответ = self._кандидаты

    def fetchall(self) -> list[Any]:
        return self._ответ


_ЗАПИСИ = [("CLN03", "D1", "hot_kitchen", "грязный пол"), ("PRD01", "D2", "fridge", "нет даты")]


def test_один_набор_записей_в_другом_порядке_это_дубль() -> None:
    курсор = _Курсор(
        {_СВОЙ: _ЗАПИСИ, _ЧУЖОЙ: list(reversed(_ЗАПИСИ))}, [(_ЧУЖОЙ, date(2026, 11, 3))]
    )

    найден = find_duplicate(курсор, _СВОЙ)

    assert найден == (_ЧУЖОЙ, date(2026, 11, 3))


def test_иной_текст_записи_не_дубль() -> None:
    другие = [(*_ЗАПИСИ[0][:3], "чистый пол"), _ЗАПИСИ[1]]
    курсор = _Курсор({_СВОЙ: _ЗАПИСИ, _ЧУЖОЙ: другие}, [(_ЧУЖОЙ, date(2026, 11, 3))])

    assert find_duplicate(курсор, _СВОЙ) is None


def test_лишняя_запись_не_дубль() -> None:
    курсор = _Курсор(
        {_СВОЙ: _ЗАПИСИ, _ЧУЖОЙ: [*_ЗАПИСИ, ("CLN09", "D1", "hall", "пыль")]},
        [(_ЧУЖОЙ, date(2026, 11, 3))],
    )

    assert find_duplicate(курсор, _СВОЙ) is None


def test_проверка_без_записей_дублем_не_считается() -> None:
    курсор = _Курсор({_СВОЙ: [], _ЧУЖОЙ: []}, [(_ЧУЖОЙ, date(2026, 11, 3))])

    assert find_duplicate(курсор, _СВОЙ) is None
    assert not same_findings(signature([]), signature([]))


def test_без_кандидатов_в_окне_дубля_нет() -> None:
    курсор = _Курсор({_СВОЙ: _ЗАПИСИ}, [])

    assert find_duplicate(курсор, _СВОЙ) is None
