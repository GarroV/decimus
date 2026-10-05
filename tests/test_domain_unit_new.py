"""Новая пиццерия из веб-админки: какое имя заводится и когда отказ (#437, D233, D240).

Ядро: имя уходит в справочник сети и дальше в историю проверок как факт.
Ошибка здесь тихая — «Yerevan-4», заведённая в Сербии, выглядит законной
точкой и собирает проверки не той страны.
"""

from __future__ import annotations

import pytest

from src.domain import unit_new
from src.domain.tenants import may_add_units
from src.domain.unit_name import UNIT_NAME_LIMIT
from src.domain.unit_new import NewUnit, NewUnitRefused, plan_new_unit


def отказ(написано: str, страна: str) -> NewUnitRefused:
    with pytest.raises(NewUnitRefused) as пойман:
        plan_new_unit(написано, country=страна)
    return пойман.value


def test_написанное_сводится_к_городу_N_и_становится_синонимом() -> None:
    assert plan_new_unit("  Белград   6 ", country="rs") == NewUnit(
        name="Belgrade-6", country="RS", city="beograd", typed="Белград 6"
    )
    assert plan_new_unit("Белград 6", country="RS").aliases == ("Белград 6",)


def test_каноническое_написание_синонимом_не_становится() -> None:
    assert plan_new_unit("Belgrade-6", country="RS").aliases == ()


def test_город_другой_страны_отказ_с_именем_и_страной() -> None:
    пойман = отказ("Ереван-4", "RS")
    assert пойман.code == unit_new.OTHER_COUNTRY
    assert пойман.params == {"name": "Yerevan-4", "country": "AM"}


def test_незнакомый_город_не_отказ_но_помечен() -> None:
    # D240: новый город заводится, но экран обязан переспросить.
    план = plan_new_unit("Кутаиси-1", country="GE")
    assert план.name == "Kutaisi-1" and not план.known_city and план.country == "GE"
    assert plan_new_unit("Batumi-3", country="GE").known_city


@pytest.mark.parametrize(
    ("написано", "страна", "код"),
    [
        ("", "RS", unit_new.EMPTY),
        ("   ", "RS", unit_new.EMPTY),
        ("Земун", "RS", unit_new.NEED_NUMBER),
        ("Belgrade", "RS", unit_new.NEED_NUMBER),
        ("Belgrade-6", "ZZ", unit_new.UNKNOWN_COUNTRY),
        ("Belgrade-6", "", unit_new.UNKNOWN_COUNTRY),
        ("П" * UNIT_NAME_LIMIT + "-1", "RS", unit_new.TOO_LONG),
        ("🍕" * 40 + "-1", "RS", unit_new.TOO_LONG),
        # Латиница длиннее написанного: «Щ» → «shch».
        ("Щ" * (UNIT_NAME_LIMIT - 3) + "-1", "RS", unit_new.TOO_LONG),
    ],
)
def test_отказы(написано: str, страна: str, код: str) -> None:
    assert отказ(написано, страна).code == код


def test_заводит_только_уК() -> None:
    assert may_add_units("HQ") and may_add_units("default")
    assert not may_add_units("GE") and not may_add_units("")
