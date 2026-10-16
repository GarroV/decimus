"""Номер точки Dodo IS для записи справочника, названной адресом (D517, #909).

Ядро: неверное сопоставление молча переименует точку чужим номером и склеит
историю проверок двух пиццерий под одним именем.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.domain.unit_match import (
    DodoUnit,
    Match,
    claimed_twice,
    match_unit,
    merge_registry,
    official_name,
    parse_dodo_units,
)


def _unit(uuid: str, name: str, street: str, house: str, alias: str = "", **kw: Any) -> DodoUnit:
    return DodoUnit(
        uuid=uuid,
        name=name,
        country="KG",
        state=kw.get("state", 1),
        alias=alias,
        translit_alias=kw.get("translit", ""),
        address=f"{street}, {house}",
        locality="Бишкек",
        street=street,
        house=house,
    )


BISHKEK = [
    _unit("a" * 32, "Bishkek-8", "проспект Манаса", "7", "Манаса 7, ББ"),
    _unit("b" * 32, "Bishkek-9", "проспект Чынгыза Айтматова", "57", "Политех"),
    _unit("c" * 32, "Bishkek-12", "проспект Чынгыза Айтматова", "3", "ТРЦ Азия Молл"),
    _unit("d" * 32, "Bishkek-7", "проспект Чуй", "32Б", "Восток-5"),
    _unit("e" * 32, "Bishkek-14", "проспект Чуй", "186", "Молодая Гвардия", state=0),
]


@pytest.mark.parametrize(
    ("записано", "номер"),
    [
        ("Bishkek — 7 Manas Ave", "Bishkek-8"),
        ("Bishkek — 57 Prospekt Chyngyza Aytmatova", "Bishkek-9"),
        ("Bishkek — 3 Prospekt Chyngyza Aytmatova", "Bishkek-12"),
        ("Bishkek — Чуйский переулок 32Б", "Bishkek-7"),
        ("Bishkek — 186 Chuy Ave", "Bishkek-14"),
    ],
)
def test_адрес_находит_ровно_свою_точку(записано: str, номер: str) -> None:
    найдено = match_unit(записано, None, BISHKEK)

    assert найдено.unit is not None
    assert найдено.unit.name == номер
    assert найдено.how == "адрес"


def test_тот_же_номер_дома_на_другой_улице_не_совпадение() -> None:
    # Дом 7 есть и на Манаса; улица Фрунзе — другая точка, которой в списке нет.
    найдено = match_unit("Bishkek — 7 Frunze St", None, BISHKEK)

    assert найдено.unit is None
    assert "не найдена" in найдено.reason


def test_та_же_улица_с_другим_номером_дома_не_совпадение() -> None:
    найдено = match_unit("Bishkek — 99 Manas Ave", None, BISHKEK)

    assert найдено.unit is None


def test_алиас_находит_точку_по_району() -> None:
    точки = [_unit("f" * 32, "Abuja-3", "Pa Michael Imoudu Avenue", "", "Gwarimpa")]

    найдено = match_unit("Gwarimpa", None, точки)

    assert найдено.unit is not None
    assert найдено.unit.name == "Abuja-3"
    assert найдено.how == "алиас"


def test_два_кандидата_это_неоднозначно_а_не_первый() -> None:
    точки = [
        _unit("1" * 32, "Podgorica-1", "Moskovska", "1", "Podgorica"),
        _unit("2" * 32, "Podgorica-2", "Jovana Tomasevica", "2", "Podgorica"),
    ]

    найдено = match_unit("Podgorica", None, точки)

    assert найдено.unit is None
    assert "неоднозначно" in найдено.reason


def test_code_записи_главнее_написанного_имени() -> None:
    найдено = match_unit("что-то совсем другое", "A" * 32, BISHKEK)

    assert найдено.unit is not None
    assert найдено.unit.name == "Bishkek-8"
    assert найдено.how == "code"


def test_code_записи_расходится_с_найденным_по_адресу_не_трогаем() -> None:
    найдено = match_unit("Bishkek — 7 Manas Ave", "9" * 32, BISHKEK)

    assert найдено.unit is None
    assert "code" in найдено.reason


def test_две_записи_на_одну_точку_обе_остаются_как_были() -> None:
    точка = BISHKEK[0]
    совпадения = {1: Match(точка, "адрес"), 2: Match(точка, "алиас"), 3: Match(BISHKEK[1], "адрес")}

    итог = claimed_twice(совпадения)

    assert итог[1].unit is None
    assert итог[2].unit is None
    assert "две записи" in итог[1].reason
    assert итог[3].unit is BISHKEK[1]


def test_латинский_номер_берётся_как_есть_кириллический_сводится_к_канону() -> None:
    дубай = _unit("7" * 32, "Dubai 3-1", "Jumeirah Street", "60")
    бишкек = _unit("8" * 32, "Бишкек-17", "улица Ибраимова", "106")

    assert official_name(дубай)[0] == "Dubai 3-1"  # не Dubai-1: склеило бы точки
    assert official_name(бишкек) == ("Bishkek-17", "bishkek")


def test_свод_даёт_номер_а_api_адрес() -> None:
    api = parse_dodo_units(
        "KG",
        [
            {
                "Type": 1,
                "UUId": "A" * 32,
                "Name": "Бишкек-8",
                "State": 1,
                "Alias": "Манаса 7",
                "AddressDetails": {"StreetName": "проспект Манаса", "HouseNumber": "7"},
            },
            {"Type": 2, "UUId": "B" * 32, "Name": "Склад"},
        ],
    )
    свод = [("a" * 32, "KG", "Bishkek-8", False), ("c" * 32, "KG", "Bishkek-20", True)]

    кандидаты = merge_registry(свод, api)

    by_uuid = {c.uuid: c for c in кандидаты}
    assert len(кандидаты) == 2  # склад не пиццерия
    assert by_uuid["a" * 32].name == "Bishkek-8"  # номер из свода
    assert by_uuid["a" * 32].state == 0
    assert by_uuid["a" * 32].street == "проспект Манаса"  # адрес из API
    assert by_uuid["c" * 32].street == ""  # в API нет: годится только по code
    assert match_unit("Bishkek — 7 Manas Ave", None, кандидаты).unit is by_uuid["a" * 32]
