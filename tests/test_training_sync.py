"""Загрузка обучения (D575, #906): в базу уходят только счётчики, в лог — только числа.

Это граница «данных о сотрудниках нет»: тест подкладывает результаты с узнаваемыми
идентификаторами людей и ищет их во всём, что загрузчик отдал базе и логу.
"""

from __future__ import annotations

import logging
from dataclasses import fields, is_dataclass
from datetime import date
from typing import Any

import pytest
from test_training_departments import KNOWN, _tree

from src.domain.training_metrics import Counters, Result
from src.learning import sync
from src.learning.ispring import Client

PEOPLE = ["staff-4711-ivanov", "staff-4712-petrova", "staff-4713-sidorov"]


class FakeClient:
    """Подменяет `Client`: дерево подразделений и результаты по подразделению."""

    def __init__(self, by_dept: dict[str, list[Result]]) -> None:
        self.by_dept = by_dept
        self.asked: list[str] = []

    def departments(self):
        return _tree()

    def results(self, department_id: str):
        self.asked.append(department_id)
        rows = self.by_dept.get(department_id, [])
        return rows, {r.course_id: f"Курс {r.course_id}" for r in rows}, 0


def _rows() -> dict[str, list[Result]]:
    return {
        "ro-1": [
            Result(PEOPLE[0], "c1", "complete", time_spent=300),
            Result(PEOPLE[0], "c2", "passed"),
            Result(PEOPLE[1], "c1", "not_started", is_overdue=True),
        ],
        "am-1": [Result(PEOPLE[2], "c1", "failed")],
    }


@pytest.fixture
def saved(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {}
    monkeypatch.setattr(
        sync.learning_store, "known_units", lambda: [(k.dodo_id, k.name, k.country) for k in KNOWN]
    )

    def save(on_date, departments, totals, courses, titles):
        box.update(
            on_date=on_date, departments=departments, totals=totals, courses=courses, titles=titles
        )

    monkeypatch.setattr(sync.learning_store, "save_snapshot", save)
    return box


def _walk(value: Any) -> list[Any]:
    """Все листья структуры: строки и числа из словарей, кортежей и датаклассов."""
    if is_dataclass(value) and not isinstance(value, type):
        return [leaf for f in fields(value) for leaf in _walk(getattr(value, f.name))]
    if isinstance(value, dict):
        return [leaf for k, v in value.items() for leaf in (*_walk(k), *_walk(v))]
    if isinstance(value, (list, tuple, set)):
        return [leaf for v in value for leaf in _walk(v)]
    return [value]


def test_в_базу_уходят_только_счётчики_без_людей(saved: dict[str, Any]) -> None:
    sync.run(FakeClient(_rows()), today=date(2026, 10, 20))  # type: ignore[arg-type]
    leaves = [
        str(x)
        for x in _walk([saved["totals"], saved["courses"], saved["titles"], saved["departments"]])
    ]
    for person in PEOPLE:
        assert not any(person in leaf for leaf in leaves), person
    assert all(isinstance(c, Counters) for c in saved["totals"].values())
    assert all(isinstance(c, Counters) for c in saved["courses"].values())


def test_в_лог_не_попадают_идентификаторы_людей(
    saved: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        sync.run(FakeClient(_rows()), today=date(2026, 10, 20))  # type: ignore[arg-type]
    assert caplog.records
    text = "\n".join(r.getMessage() for r in caplog.records)
    for person in PEOPLE:
        assert person not in text


def test_итог_по_пиццерии_и_по_курсу() -> None:
    from src.domain.training_metrics import aggregate

    agg = aggregate(_rows()["ro-1"])
    assert (agg.total.assigned, agg.total.completed, agg.total.overdue) == (3, 2, 1)
    assert (agg.total.people_total, agg.total.people_trained) == (2, 1)


def test_читаются_только_пиццерии_без_офисов_и_стран(saved: dict[str, Any]) -> None:
    client = FakeClient(_rows())
    summary = sync.run(client, today=date(2026, 10, 20))  # type: ignore[arg-type]
    assert sorted(client.asked) == ["am-1", "ee-2", "ro-1"]
    assert summary.pizzerias == 3
    assert summary.matched == 2  # Tallinn-12 нет среди пиццерий рейтингов
    assert summary.results == 4


def test_несопоставленная_пиццерия_попадает_в_снимок(saved: dict[str, Any]) -> None:
    sync.run(FakeClient(_rows()), today=date(2026, 10, 20))  # type: ignore[arg-type]
    unit_ids = {d[0]: d[5] for d in saved["departments"]}
    assert unit_ids["ee-2"] is None
    assert "ee-2" in saved["totals"]


def test_сбой_на_пиццерии_не_кладёт_полснимка(
    saved: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.learning.ispring import IspringError

    class Broken(FakeClient):
        def results(self, department_id: str):
            if department_id == "am-1":
                raise IspringError("iSpring ответил 500 на /learners/results")
            return super().results(department_id)

    with pytest.raises(IspringError):
        sync.run(Broken(_rows()), today=date(2026, 10, 20))  # type: ignore[arg-type]
    assert saved == {}


def test_клиент_подходит_под_утиную_подмену() -> None:
    assert hasattr(Client, "departments") and hasattr(Client, "results")
