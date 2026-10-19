"""Выбор пунктов и зон для правки на вычитке (D535): из чек-листа версии, по его порядку.

Ошибка здесь молчаливая: пункт нарушения, которого нет в выборе, нельзя выбрать,
а лишний (информационный вопрос) записался бы нарушением.
"""

from __future__ import annotations

from src.web.review import build_sheet

ЗОНЫ = (
    {"code": "hall", "name_ru": "Зал", "name_en": "Hall"},
    {"code": "hot_kitchen", "name_ru": "Зона Б", "name_en": "Zone B"},
)


def _пункт(
    code: str, kind: str, ru: str, en: str, zones: str, levels: str = "D1;D2"
) -> dict[str, str]:
    return {
        "id": code,
        "kind": kind,
        "question_ru": ru,
        "question_en": en,
        "zones": zones,
        "levels": levels,
    }


ПУНКТЫ = (
    _пункт("CLN05", "violation", "Грязный пол", "Dirty floor", "*"),
    _пункт("PRD01", "violation", "Просрочка", "Expired", "hot_kitchen", "d2, D3"),
    _пункт("INF01", "info", "Смена", "Shift", "*", ""),
)


def test_в_выбор_идут_только_пункты_нарушений_в_порядке_версии() -> None:
    лист = build_sheet(items=ПУНКТЫ, zones=ЗОНЫ, lang="ru")

    assert [p.code for p in лист.picks] == ["CLN05", "PRD01"]
    assert [z.name for z in лист.zones] == ["Зал", "Зона Б"]


def test_классы_и_зоны_пункта_берутся_из_версии() -> None:
    пол, просрочка = build_sheet(items=ПУНКТЫ, zones=ЗОНЫ, lang="ru").picks

    # «Во всех зонах» раскрывается в зоны версии; классы — как их читает движок.
    assert (пол.levels, пол.zones) == (("D1", "D2"), ("hall", "hot_kitchen"))
    assert (просрочка.levels, просрочка.zones) == (("D2", "D3"), ("hot_kitchen",))


def test_язык_интерфейса_выбирает_подписи() -> None:
    лист = build_sheet(items=ПУНКТЫ, zones=ЗОНЫ, lang="en")

    assert лист.picks[0].question == "Dirty floor"
    assert лист.zones[1].name == "Zone B"
