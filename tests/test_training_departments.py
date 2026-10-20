"""Дерево подразделений iSpring → страны, пиццерии, офисы; сопоставление с рейтингами (#906)."""

from __future__ import annotations

import pytest

from src.learning import departments as dp
from src.learning.ispring import Department
from src.ratings.matching import KnownUnit


def _tree() -> list[Department]:
    def d(i: str, name: str, parent: str | None) -> Department:
        return Department(i, name, parent, None)

    return [
        d("root", "Dodo Brands", None),
        d("pizza", "Dodo Pizza", "root"),
        d("drink", "Drinkit", "root"),
        d("ro", "Dodo Pizza - Romania", "pizza"),
        d("am", "Dodo Pizza - Armenia", "pizza"),
        d("ee", "Dodo Pizza - Estonia", "pizza"),
        d("md", "Dodo Pizza - Moldova", "pizza"),
        d("zz", "Dodo Pizza - Atlantis", "pizza"),
        d("ro-1", "Brasov-1: Brasov - Dodo Pizza", "ro"),
        d("am-1", "Vagharshapat-1", "am"),
        d("ee-office", "Kontor: Tallinn - Dodo Pizza", "ee"),
        d("ee-2", "Tallinn-12: Tallinn - Dodo Pizza", "ee"),
        d("ro-office", "Antalya Office", "ro"),
        d("dk", "Drinkit - Russia", "drink"),
        d("dk-1", "Moscow-1: Moscow", "dk"),
        d("zz-1", "Lost-1: Lost - Dodo Pizza", "zz"),
        d("deep", "Cashiers", "ro-1"),
    ]


KNOWN = [
    KnownUnit("a" * 32, "Brasov-1", "RO"),
    KnownUnit("b" * 32, "Vagharshapat-1", "AM"),
]


def _by_id(rows: list[dp.Mapped]) -> dict[str, dp.Mapped]:
    return {m.id: m for m in rows}


def test_короткое_имя_до_двоеточия() -> None:
    assert dp.short_name("Brasov-1: Brasov - Dodo Pizza") == "Brasov-1"
    assert dp.short_name("Vagharshapat-1") == "Vagharshapat-1"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Brasov-1: Brasov - Dodo Pizza", True),
        ("Vagharshapat-1", True),
        ("Tallinn-12: Tallinn - Dodo Pizza", True),
        ("Kontor: Tallinn - Dodo Pizza", False),
        ("Antalya Office", False),
    ],
)
def test_пиццерия_это_название_с_номером_точки(name: str, expected: bool) -> None:
    assert dp.is_pizzeria_name(name) is expected


def test_виды_подразделений() -> None:
    mapped, _ = dp.map_departments(_tree(), KNOWN)
    kinds = {m.id: m.kind for m in mapped}
    assert kinds["ro"] == dp.KIND_COUNTRY
    assert kinds["ro-1"] == kinds["am-1"] == kinds["ee-2"] == dp.KIND_PIZZERIA
    assert kinds["ee-office"] == kinds["ro-office"] == dp.KIND_OFFICE


def test_страна_берётся_из_названия_родителя() -> None:
    mapped = _by_id(dp.map_departments(_tree(), KNOWN)[0])
    assert (mapped["ro"].country_code, mapped["ro-1"].country_code) == ("RO", "RO")
    assert mapped["am-1"].country_code == "AM"


def test_сопоставление_с_рейтингами_по_короткому_имени_и_стране() -> None:
    mapped = _by_id(dp.map_departments(_tree(), KNOWN)[0])
    assert mapped["ro-1"].unit_dodo_id == "a" * 32
    assert mapped["am-1"].unit_dodo_id == "b" * 32
    assert mapped["ee-2"].unit_dodo_id is None  # нет в рейтингах — остаётся и не теряется


def test_название_пиццерии_без_хвоста_после_двоеточия() -> None:
    mapped = _by_id(dp.map_departments(_tree(), KNOWN)[0])
    assert mapped["ro-1"].title == "Brasov-1"


def test_чужие_бренды_вне_объёма() -> None:
    ids = {m.id for m in dp.map_departments(_tree(), KNOWN)[0]}
    assert not ids & {"drink", "dk", "dk-1", "root", "pizza"}


def test_страна_вне_справочника_и_подразделение_глубже_считаются_а_не_теряются() -> None:
    mapped, ignored = dp.map_departments(_tree(), KNOWN)
    ids = {m.id for m in mapped}
    assert not ids & {"zz", "zz-1", "deep"}
    assert ignored == 3  # Atlantis, её пиццерия и подразделение внутри пиццерии


def test_молдова_есть_в_iSpring_и_нет_в_справочнике_сети() -> None:
    mapped = _by_id(dp.map_departments(_tree(), KNOWN)[0])
    assert mapped["md"].country_code == "MD"
