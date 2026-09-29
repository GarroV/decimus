"""Имя пиццерии «Город-N» по-английски из написанного как угодно (D233).

Ядро: имя точки уходит в историю сети и в отчёт как факт. Ошибка здесь тихая —
«Ереван-2», сведённый не к той точке, выглядит правдоподобной записью.
"""

from __future__ import annotations

import pytest

from src.domain.unit_name import UnitName, canonical_unit


@pytest.mark.parametrize(
    ("написано", "имя", "город", "страна"),
    [
        ("Yerevan-2", "Yerevan-2", "yerevan", "AM"),
        ("Ереван-2", "Yerevan-2", "yerevan", "AM"),
        ("ереван 2", "Yerevan-2", "yerevan", "AM"),
        ("Erevan-2", "Yerevan-2", "yerevan", "AM"),
        ("Երևան 1", "Yerevan-1", "yerevan", "AM"),
        ("Белград-5", "Belgrade-5", "beograd", "RS"),
        ("Beograd 5", "Belgrade-5", "beograd", "RS"),
        ("Нови Сад-3", "Novi Sad-3", "novisad", "RS"),
        ("novi sad 3", "Novi Sad-3", "novisad", "RS"),
        ("Подгорица-2", "Podgorica-2", "podgorica", "ME"),
        ("ПОдгорица-2", "Podgorica-2", "podgorica", "ME"),
        ("İzmir-10", "Izmir-10", "izmir", "TR"),
        ("Бишкек №3", "Bishkek-3", "bishkek", "KG"),
        ("Тбилиси -1", "Tbilisi-1", "tbilisi", "GE"),
        ("Варшава-02", "Warsaw-2", "warszawa", "PL"),
        ("Стара Загора 1", "Stara Zagora-1", "starazagora", "BG"),
    ],
)
def test_написанное_на_любом_языке_сводится_к_английскому(
    написано: str, имя: str, город: str, страна: str
) -> None:
    assert canonical_unit(написано) == UnitName(name=имя, city=город, country=страна)


@pytest.mark.parametrize(
    ("написано", "имя"),
    [
        ("Еревна-2", "Yerevan-2"),
        ("Подгорца 2", "Podgorica-2"),
        ("Belgrad-5", "Belgrade-5"),
        ("Bishkeck-1", "Bishkek-1"),
    ],
)
def test_опечатка_в_городе_не_мешает(написано: str, имя: str) -> None:
    найдено = canonical_unit(написано)
    assert найдено is not None and найдено.name == имя


def test_незнакомый_город_пишется_латиницей_без_страны() -> None:
    # Кутаиси в сети пока нет — точка всё равно получает английское имя.
    assert canonical_unit("Кутаиси-1") == UnitName(name="Kutaisi-1", city=None, country=None)


@pytest.mark.parametrize("написано", ["Земун", "Yerevan", "Berceni", "", "   ", "12"])
def test_без_города_и_номера_имени_нет(написано: str) -> None:
    # «Город-N» без номера не бывает: такое написание не имя точки.
    assert canonical_unit(написано) is None


def test_короткое_похожее_не_подменяет_город() -> None:
    # «Бари» — не черногорский Бар и не Бали: слишком далеко для опечатки.
    найдено = canonical_unit("Бари-1")
    assert найдено is not None and найдено.city is None
