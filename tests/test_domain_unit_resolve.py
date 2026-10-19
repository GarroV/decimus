"""D538: одно правило имени пиццерии — найти по любому написанию, завести под именем справочника.

Ядро: ошибка здесь не кричит — пиццерия молча заводится вторым экземпляром под кириллицей, и
история рассыпается по написаниям. Чистая логика без базы; двери (бот, мини-апп, MCP, админка,
слив) проверяются на своих границах в соседних файлах.
"""

from __future__ import annotations

import pytest

from src.domain.unit_match import Ref
from src.domain.unit_name import canonical_unit
from src.domain.unit_resolve import DirUnit, find_reference, find_unit, with_reference

ТБИЛИСИ = DirUnit(id="t1", name="Tbilisi-1", anchored=True)
СПРАВОЧНИК = (
    ТБИЛИСИ,
    DirUnit(id="t2", name="Tbilisi-2", anchored=True),
    # Кириллические дубли, снятые `make units-normalize --retire`: ведут на латинские.
    DirUnit(id="c1", name="Тбилиси-1", merged_into="t1"),
    DirUnit(id="c1b", name="Тбилиси -1", merged_into="t1"),
    DirUnit(id="c2", name="Тбилиси-2", merged_into="t2"),
)
ЭТАЛОН = (
    Ref("GE", "Tbilisi-1", "aa" * 16, "Tbilisi"),
    Ref("RS", "Belgrade-1", "bb" * 16, "Belgrade"),
    Ref("KG", "Bishkek-8", "cc" * 16, "Bishkek"),
)


@pytest.mark.parametrize(
    "написано", ["Тбилиси-1", "тбилиси 1", "Tbilisi 1", "Тбилиси -1", "TBILISI–1"]
)
def test_любое_написание_находит_латинскую_точку(написано: str) -> None:
    найдено = find_unit(СПРАВОЧНИК, написано)

    assert найдено.unit == ТБИЛИСИ


def test_имя_снятой_точки_ведёт_на_живую_а_не_на_себя() -> None:
    найдено = find_unit(СПРАВОЧНИК, "Тбилиси-2")

    assert найдено.unit is not None and найдено.unit.id == "t2"
    assert найдено.unit.merged_into is None


def test_имя_снятой_точки_без_общего_написания_находит_живую() -> None:
    # «Dubravka» влита в «Belgrade-1» картой имён: общего с ней написания у цели нет.
    справочник = (
        DirUnit(id="b1", name="Belgrade-1", anchored=True),
        DirUnit(id="d", name="Dubravka", merged_into="b1"),
    )

    найдено = find_unit(справочник, "dubravka")

    assert найдено.unit == справочник[0]


def test_снятая_без_живой_цели_ничего_не_называет() -> None:
    сирота = (DirUnit(id="c", name="Тбилиси-1", merged_into="нет-такой"),)

    assert find_unit(сирота, "Тбилиси-1").unit is None


def test_чужой_номер_не_находится() -> None:
    assert find_unit(СПРАВОЧНИК, "Тбилиси-3").unit is None


def test_две_разные_живые_точки_подряд_не_угадываются() -> None:
    две = (DirUnit(id="a", name="Zagreb-1"), DirUnit(id="b", name="ZAGREB 1"))

    найдено = find_unit(две, "загреб-1")

    assert найдено.unit is None and найдено.ambiguous


def test_точка_справочника_сети_сильнее_дубля_по_факту_проверки() -> None:
    дубли = (
        DirUnit(id="d", name="Тбилиси-1"),
        DirUnit(id="t", name="Tbilisi-1", anchored=True),
    )

    assert find_unit(дубли, "Тбилиси-1").unit == дубли[1]


@pytest.mark.parametrize("написано", ["Тбилиси-1", "тбилиси 1", "Tbilisi 1", "Тбилиси -1"])
def test_новая_точка_кириллицей_заводится_под_латинским_именем_справочника(написано: str) -> None:
    имя = canonical_unit(написано)
    assert имя is not None

    итог = with_reference(имя, написано, ЭТАЛОН)

    assert (итог.name, итог.code, итог.country) == ("Tbilisi-1", "aa" * 16, "GE")


def test_незнакомый_словарю_город_заводится_латиницей_справочника() -> None:
    # Справочник пиццерий знает строку: имя и код Dodo берутся оттуда.
    эталон = (Ref("KG", "Bishkek-8", "ee" * 16, "Bishkek"),)
    имя = canonical_unit("Бишкек 8")
    assert имя is not None

    итог = with_reference(имя, "Бишкек 8", эталон)

    assert (итог.name, итог.code) == ("Bishkek-8", "ee" * 16)


def test_справочник_не_знает_строку_имя_остаётся_каноническим() -> None:
    имя = canonical_unit("Белград-7")
    assert имя is not None

    assert with_reference(имя, "Белград-7", ЭТАЛОН) == имя


def test_строка_другой_страны_не_подставляется() -> None:
    имя = canonical_unit("Tbilisi-1")
    assert имя is not None

    assert find_reference("Tbilisi-1", ЭТАЛОН, country="RS") is None


def test_две_строки_справочника_подряд_не_угадываются() -> None:
    дубли = (Ref("GE", "Tbilisi-1", "1"), Ref("GE", "Tbilisi - 1", "2"))

    assert find_reference("Тбилиси-1", дубли, country="GE") is None
