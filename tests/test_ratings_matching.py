"""Пиццерия без id сопоставляется по имени (D323) — тем же разбором, что в боте.

Ошибка здесь молчит: балл ляжет в чужую пиццерию и будет выглядеть правдой.
Поэтому номер точки не угадывается никогда, а неоднозначность — это «нет».
"""

from __future__ import annotations

from src.ratings.matching import KnownUnit, match_unit

ИЗВЕСТНЫЕ = (
    KnownUnit("a1" * 16, "Beograd-1", "RS"),
    KnownUnit("a2" * 16, "Beograd-2", "RS"),
    KnownUnit("b1" * 16, "Ljubljana-1", "SI"),
    KnownUnit("c1" * 16, "Batumi-1", "GE"),
)


def test_точное_имя_после_нормализации() -> None:
    assert match_unit("  beograd-1 ", "RS", ИЗВЕСТНЫЕ) == "a1" * 16


def test_русское_и_английское_написание_города() -> None:
    assert match_unit("Белград 2", "RS", ИЗВЕСТНЫЕ) == "a2" * 16
    assert match_unit("Belgrade-1", "RS", ИЗВЕСТНЫЕ) == "a1" * 16


def test_опечатка_в_городе_допускается() -> None:
    assert match_unit("Ljubljna-1", "SI", ИЗВЕСТНЫЕ) == "b1" * 16


def test_другой_номер_не_угадывается() -> None:
    assert match_unit("Belgrade-7", "RS", ИЗВЕСТНЫЕ) is None


def test_другой_номер_соседа_не_цепляется_и_без_ничьей() -> None:
    одна = (KnownUnit("a1" * 16, "Beograd-1", "RS"),)
    assert match_unit("Belgrade-7", "RS", одна) is None


def test_чужая_страна_не_сопоставляется() -> None:
    assert match_unit("Batumi-1", "RS", ИЗВЕСТНЫЕ) is None


def test_пустое_имя_нет() -> None:
    assert match_unit("   ", None, ИЗВЕСТНЫЕ) is None


def test_двусмысленность_нет() -> None:
    дубли = (*ИЗВЕСТНЫЕ, KnownUnit("a9" * 16, "beograd-1", "RS"))
    assert match_unit("Beograd-1", "RS", дубли) is None
