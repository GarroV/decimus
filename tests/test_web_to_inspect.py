"""«Где нужно проверить» на экране «Календарь» (D466): отбор точек, охват, показ.

Блок переехал с «Главной» (D418), затем с «Проверок» (D466); логика та же (D399).
С D477 экран «Календарь» его не рисует и не читает (`app.SHOW_TO_CHECK`), код живёт.
Сторожится:
кто попадает в ряд и в каком порядке, что чтение идёт в охвате вошедшего, что
пустой блок не показывается, а отказ базы называется строкой, а не тишиной.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.db.errors import DbError
from src.db.reach import Reach
from src.web import to_inspect


def test_отбирает_точки_без_проверок_за_период() -> None:
    """Проверенные за период не попадают; ни разу не проверенные — первыми, затем давнее всех."""
    # Arrange
    строки = [
        ("Свежая", "c1", date(2026, 9, 20), 1),
        ("Давняя", "c2", date(2026, 3, 1), 0),
        ("Недавняя", "c3", date(2026, 8, 1), 0),
        ("Новая", "c4", None, 0),
        ("Чужая страна", "c5", None, 0),
    ]
    гео = {n: ("RS", "") for n, *_ in строки} | {"Чужая страна": ("GE", "")}

    # Act
    ждут, ещё = to_inspect.pick_units(строки, geo=гео, ids={}, country="RS")

    # Assert
    assert [т.unit for т in ждут] == ["Новая", "Давняя", "Недавняя"]
    assert ещё == 0


def test_ряд_ограничен_остаток_числом() -> None:
    строки = [(f"П-{n:02d}", "", None, 0) for n in range(to_inspect.TO_CHECK_TOP + 3)]

    ждут, ещё = to_inspect.pick_units(строки, geo={}, ids={})

    assert len(ждут) == to_inspect.TO_CHECK_TOP and ещё == 3


def test_отбор_по_городу_и_части_названия() -> None:
    строки = [("Белград-1", "", None, 0), ("Белград-2", "", None, 0), ("Нови-Сад-1", "", None, 0)]
    гео = {
        "Белград-1": ("RS", "beograd"),
        "Белград-2": ("RS", "beograd"),
        "Нови-Сад-1": ("RS", "ns"),
    }

    ждут, _ = to_inspect.pick_units(строки, geo=гео, ids={}, city="beograd", query="2")

    assert [т.unit for т in ждут] == ["Белград-2"]


class _База:
    """Слой базы, запоминающий охват и окно, с которыми его позвали."""

    def __init__(self) -> None:
        self.звал: dict[str, object] = {}

    def unit_geography(self, **kw: object) -> dict[str, tuple[str, str]]:
        return {"Н": ("GE", "")}

    def unit_ids(self, **kw: object) -> dict[str, str]:
        return {}

    def unit_last_inspections(self, **kw: object) -> list[tuple[str, str, date | None, int]]:
        self.звал = kw
        return [("Н", "c", None, 0)]


def test_читается_в_охвате_вошедшего_и_в_периоде_реестра(monkeypatch: pytest.MonkeyPatch) -> None:
    """Партнёр получает точки только своего охвата: запрос зовут с его `reach` и окном реестра."""
    # Arrange
    база = _База()
    monkeypatch.setattr(to_inspect, "queries", база)
    партнёр = Reach(tenant="GE", tenants=None, countries=("GE",))

    # Act
    блок = to_inspect.load(reach=партнёр, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))

    # Assert
    assert база.звал["reach"] == партнёр
    assert (база.звал["date_from"], база.звал["date_to"]) == (date(2026, 9, 1), date(2026, 9, 30))
    assert [т.unit for т in блок.units] == ["Н"]


def test_отказ_базы_блок_называет_а_не_прячет(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    class Отказ(_База):
        def unit_geography(self, **kw: object) -> dict[str, tuple[str, str]]:
            raise DbError("нет связи")

    monkeypatch.setattr(to_inspect, "queries", Отказ())

    # Act
    блок = to_inspect.load(reach=Reach("HQ", None, None), date_from=None, date_to=None)

    # Assert
    assert блок.failed and блок.shown
