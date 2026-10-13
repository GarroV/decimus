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


ТУРЕЦКИЕ = (
    KnownUnit("d1" * 16, "Izmir-4", "TR"),
    KnownUnit("d2" * 16, "Eskisehir-1", "TR"),
    KnownUnit("d3" * 16, "Mugla-1", "TR"),
    KnownUnit("d4" * 16, "İzmir-5", "TR"),
)


def test_турецкие_написания_одной_пиццерии_сходятся() -> None:
    for написание in ("İzmir-4", "Izmir-4", "izmir-4", "Izmır-4", "IZMIR-4", "ızmır-4"):
        assert match_unit(написание, "TR", ТУРЕЦКИЕ) == "d1" * 16, написание
    assert match_unit("Eskişehir-1", "TR", ТУРЕЦКИЕ) == "d2" * 16
    assert match_unit("Muğla-1", "TR", ТУРЕЦКИЕ) == "d3" * 16
    assert match_unit("Şç-1", "TR", (KnownUnit("e1" * 16, "Sc-1", "TR"),)) == "e1" * 16


def test_свёртка_работает_и_в_известных_пиццериях() -> None:
    известные = (KnownUnit("d5" * 16, "İzmir-4", "TR"),)
    assert match_unit("Izmir-4", "TR", известные) == "d5" * 16


def test_номер_точки_турецкого_имени_по_прежнему_обязан_совпасть() -> None:
    assert match_unit("Izmir-4", "TR", (KnownUnit("d4" * 16, "İzmir-5", "TR"),)) is None
    assert match_unit("İzmir-5", "TR", ТУРЕЦКИЕ) == "d4" * 16


def test_свёртка_имени_сводит_написания_но_не_номера() -> None:
    from src.domain.unit_name import fold_unit_name as fold_name

    одно = ["İzmir-4", "Izmir-4", "izmir-4", "Izmır-4", "IZMIR-4"]
    assert len({fold_name(x) for x in одно}) == 1
    assert fold_name("Eskişehir-1") == fold_name("Eskisehir-1")
    assert fold_name("Muğla-1") == fold_name("Mugla-1")
    assert fold_name("Izmir-4") != fold_name("İzmir-5")
