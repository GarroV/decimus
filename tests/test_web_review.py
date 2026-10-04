"""Лист вычитки (D199): записи раскладываются по пунктам чек-листа, ни одна не теряется.

«Чисто» на листе читается вычитывающим как факт о точке, поэтому ошибка здесь
молчаливая: потерянная запись выглядела бы чистым пунктом.
"""

from __future__ import annotations

from datetime import date

from src.db.models import FindingRow
from src.web.review import build_sheet

ЗОНЫ = (
    {"code": "hall", "name_ru": "Зал", "name_en": "Hall"},
    {"code": "hot_kitchen", "name_ru": "Зона Б", "name_en": "Zone B"},
)


def _пункт(code: str, kind: str, ru: str, en: str, zones: str) -> dict[str, str]:
    return {"id": code, "kind": kind, "question_ru": ru, "question_en": en, "zones": zones}


ПУНКТЫ = (
    _пункт("CLN05", "violation", "Грязный пол", "Dirty floor", "*"),
    _пункт("PRD01", "violation", "Просрочка", "Expired", "hot_kitchen"),
    _пункт("INF01", "info", "Смена", "Shift", "*"),
)


def _запись(ident: str, code: str, zone: str) -> FindingRow:
    return FindingRow(
        id=ident,
        inspection_id="i",
        unit_name="Белград-1",
        inspection_date=date(2026, 9, 25),
        n=int(ident[-1]),
        code=code,
        level="D1",
        zone=zone,
        zone_unusual=False,
        source="comment",
        lang="ru",
        text="запись",
        comment=None,
    )


def test_записи_ложатся_в_свою_зону_а_остальное_чисто() -> None:
    # Arrange
    записи = (_запись("f1", "CLN05", "hot_kitchen"),)

    # Act
    лист = build_sheet(items=ПУНКТЫ, zones=ЗОНЫ, findings=записи, lang="ru")

    # Assert — пол проверяется в обеих зонах, просрочка только в цехе,
    # информационный вопрос в лист нарушений не входит.
    зал, цех = лист.zones
    assert [(i.code, i.clean) for i in зал.items] == [("CLN05", True)]
    assert [(i.code, i.clean) for i in цех.items] == [("CLN05", False), ("PRD01", True)]
    assert (зал.name, цех.violations) == ("Зал", 1)
    assert лист.unplaced == ()


def test_запись_вне_чек_листа_не_теряется() -> None:
    # Arrange — пункт в чужой для него зоне и пункт, которого в версии нет.
    записи = (_запись("f1", "PRD01", "hall"), _запись("f2", "XXX99", "hall"))

    # Act
    лист = build_sheet(items=ПУНКТЫ, zones=ЗОНЫ, findings=записи, lang="en")

    # Assert
    assert [f.id for f in лист.unplaced] == ["f1", "f2"]
    assert all(i.clean for z in лист.zones for i in z.items)
    assert лист.zones[1].items[0].question == "Dirty floor"
