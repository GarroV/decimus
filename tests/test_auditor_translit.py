"""Имя проверяющего латиницей: автоперевод по ICAO 9303 (D644).

Ядро: имя уходит партнёру на штамп кадра и в отчёт, и неверная буква здесь —
правдоподобное, но чужое имя. Правило российских загранпаспортов; сербские и
болгарские буквы — тем же правилом плюс их собственные.
"""

from __future__ import annotations

import pytest

from src.domain.auditor_name import spell_name, transliterate


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Жульфаев Ринат", "Zhulfaev Rinat"),
        ("Хохлова Цветана", "Khokhlova Tsvetana"),
        ("Чернышёв Щукин", "Chernyshev Shchukin"),
        ("Юрий Яковлев", "Iurii Iakovlev"),
        ("Дмитрий Эльдаров", "Dmitrii Eldarov"),
        ("Подъезд Ильин", "Podieezd Ilin"),
        ("Дарья Воробьёва", "Daria Vorobeva"),
        ("Сергей Быков", "Sergei Bykov"),
    ],
)
def test_русские_имена_по_icao(source: str, expected: str) -> None:
    assert transliterate(source) == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Ђорђе Љубиша", "Djordje Ljubisha"),
        ("Његош Јован", "Njegosh Jovan"),
        ("Ћирић Џон", "Ciric Dzon"),
    ],
)
def test_сербские_буквы(source: str, expected: str) -> None:
    assert transliterate(source) == expected


def test_болгарские_буквы_при_языке_bg() -> None:
    assert transliterate("Стоянов Щерев Ъглов", lang="bg") == "Stoianov Shterev Aglov"


def test_без_языка_ъ_и_щ_читаются_по_русскому_правилу() -> None:
    assert transliterate("Щерев Ъ") == "Shcherev Ie"


def test_заглавное_слово_остаётся_заглавным() -> None:
    assert transliterate("ЖУЛЬФАЕВ Ринат") == "ZHULFAEV Rinat"


def test_латиница_не_трогается() -> None:
    assert transliterate("Rinat Zhulfaev-Smith 3rd") == "Rinat Zhulfaev-Smith 3rd"


def test_смешанное_написание() -> None:
    assert transliterate("Rinat Жульфаев") == "Rinat Zhulfaev"
    assert transliterate("Ринatt") == "Rinatt"


def test_дефис_апостроф_и_диакритика_остаются() -> None:
    assert transliterate("Анна-Мария О'Нил Ünal") == "Anna-Mariia O'Nil Ünal"


def test_пустое_остаётся_пустым() -> None:
    assert transliterate("") == ""
    assert spell_name("   ") == ""


def test_spell_name_обрезает_края_и_переводит() -> None:
    assert spell_name("  Жульфаев Ринат ") == "Zhulfaev Rinat"
