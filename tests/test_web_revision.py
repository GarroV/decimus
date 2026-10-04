"""Правка записи на приёмке (D200): исправление сверяется с чек-листом версии, считает движок."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from src.db.errors import ReviseError
from src.db.models import FindingRow, InspectionDetail, InspectionRow
from src.db.reach import reach_of
from src.domain.models import Score
from src.web import revision
from src.web.methodology import Composition

ЗАПИСЬ = "22222222-2222-2222-2222-222222222222"

СОСТАВ = Composition(
    version="v1",
    current="v1",
    latest="v1",
    items=(
        {"id": "CLN05", "kind": "violation", "levels": "D1,D2", "zones": "hot_kitchen"},
        {"id": "INF01", "kind": "info", "levels": "", "zones": "*"},
    ),
    zones=({"code": "hot_kitchen"}, {"code": "dining"}),
    versions=(),
    rates={},
)

ОЦЕНКА = Score(
    pct=90.0, grade="B", label_ru="", label_en="", counts={}, deductions=10.0, by_zone={}
)


def _проверка(*, ждёт: bool = True) -> InspectionDetail:
    строка = InspectionRow(
        id="11111111-1111-1111-1111-111111111111",
        tenant_code="HQ",
        unit_name="Белград-1",
        chat_id=1,
        kind="planned",
        inspection_date=date(2026, 9, 25),
        report_lang="ru",
        checklist_version="v1",
        pct=99.5,
        grade="A",
        findings_count=1,
        pushed_at="2026-09-25T10:00:00+00:00",
        on_review=ждёт,
    )
    запись = FindingRow(
        id=ЗАПИСЬ,
        inspection_id=строка.id,
        unit_name="Белград-1",
        inspection_date=строка.inspection_date,
        n=1,
        code="CLN05",
        level="D1",
        zone="hot_kitchen",
        zone_unusual=False,
        source="comment",
        lang="ru",
        text="грязный пол",
        comment=None,
    )
    return InspectionDetail(
        inspection=строка, deductions=0.5, counts={"D1": 1}, by_zone={}, findings=(запись,)
    )


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    журнал: dict[str, Any] = {"проверка": _проверка()}

    def прочитать(*_a: Any, **kw: Any) -> InspectionDetail:
        журнал["охват"] = kw["reach"]
        return журнал["проверка"]

    monkeypatch.setattr(revision.queries, "get_inspection", прочитать)
    monkeypatch.setattr(revision, "checklist_of", lambda *_a, **_k: СОСТАВ)
    monkeypatch.setattr(revision, "letter_sources", lambda: None)

    def пересчитать(detail: InspectionDetail, **_: Any) -> Score:
        журнал["посчитано"] = detail
        return ОЦЕНКА

    def записать(*_a: Any, **kw: Any) -> None:
        журнал["записано"] = kw

    monkeypatch.setattr(revision, "rescore", пересчитать)
    monkeypatch.setattr(revision.revise, "revise_finding", записать)
    return журнал


def _исправить(**поля: str) -> None:
    основа = {"code": "CLN05", "level": "D2", "zone": "hot_kitchen", "text": "грязный пол"}
    основа.update(поля)
    revision.revise_card(
        "11111111-1111-1111-1111-111111111111", ЗАПИСЬ, tenant="HQ", lang="ru", **основа
    )


def test_движок_считает_исправленную_запись_и_она_же_записывается(
    стенд: dict[str, Any],
) -> None:
    # Act
    _исправить(level="D2", text="  грязный пол у печи  ")

    # Assert — движку ушла исправленная запись, в базу — его оценка.
    [ушла] = стенд["посчитано"].findings
    assert (ушла.level, ушла.text) == ("D2", "грязный пол у печи")
    assert стенд["записано"]["score"] is ОЦЕНКА
    assert стенд["записано"]["revision"].zone_unusual is False
    assert стенд["записано"]["tenant"] == "HQ"


def test_чужая_проверка_из_охвата_не_исправляется(стенд: dict[str, Any]) -> None:
    """УК читает партнёра шире, чем пишет (D283): чужую ждущую — только на чтение."""
    # Arrange — охват УК отдаёт проверку партнёра
    стенд["проверка"] = replace(
        стенд["проверка"], inspection=replace(стенд["проверка"].inspection, tenant_code="demo")
    )

    # Act / Assert — отказ до движка и до записи
    with pytest.raises(ReviseError, match="своего пространства"):
        _исправить()
    assert "посчитано" not in стенд
    assert "записано" not in стенд
    assert стенд["охват"] == reach_of("HQ")


def test_зона_вне_списка_пункта_помечается_необычной(стенд: dict[str, Any]) -> None:
    _исправить(zone="dining")
    assert стенд["записано"]["revision"].zone_unusual is True


@pytest.mark.parametrize(
    ("поля", "причина"),
    [
        ({"code": "XXX99"}, "нет"),
        ({"code": "INF01"}, "нет"),
        ({"level": "D3"}, "не предусмотрен"),
        ({"zone": "moon"}, "Зоны moon"),
        ({"text": "   "}, "пуста"),
    ],
)
def test_неверное_исправление_отклоняется_до_движка(
    стенд: dict[str, Any], поля: dict[str, str], причина: str
) -> None:
    with pytest.raises(ReviseError, match=причина):
        _исправить(**поля)
    assert "посчитано" not in стенд and "записано" not in стенд


def test_у_принятой_правка_закрыта(стенд: dict[str, Any]) -> None:
    стенд["проверка"] = _проверка(ждёт=False)
    with pytest.raises(ReviseError, match="уже принята"):
        _исправить()
    assert "посчитано" not in стенд


def test_чужая_запись_не_правится(стенд: dict[str, Any]) -> None:
    проверка = _проверка()
    стенд["проверка"] = replace(проверка, findings=(replace(проверка.findings[0], id="другая"),))
    with pytest.raises(ReviseError, match="Такой записи"):
        _исправить()
