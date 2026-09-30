"""Город в шапке письма берётся и из справочника пиццерий (#460).

Мастер бота города больше не спрашивает (D233), поэтому `inspections.city`
пусто у всех новых проверок. Город живёт в справочнике (`units.city`) кодом,
и слой чтения подставляет его, когда поле проверки пустое. Письмо печатает
этот код названием на языке письма, а плашка «не восстановлен город» горит,
только если города нет нигде.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from src.db.models import InspectionDetail, InspectionRow
from src.report.letters import _cover


def _проверка(city: str) -> InspectionDetail:
    return InspectionDetail(
        inspection=InspectionRow(
            id="11111111-1111-1111-1111-111111111111",
            tenant_code="HQ",
            unit_name="Batumi-1",
            chat_id=1,
            kind="planned",
            inspection_date=date(2026, 9, 24),
            report_lang="ru",
            checklist_version="v",
            pct=85.5,
            grade="D",
            findings_count=0,
            pushed_at="2026-09-24T18:00:00+02:00",
            city=city,
        ),
        deductions=0.0,
        counts={},
        by_zone={},
        findings=(),
    )


def test_код_города_из_справочника_печатается_названием_на_языке_письма() -> None:
    шапка, пусто = _cover(_проверка("batumi"), lang="ru")
    assert шапка["city"] == "Батуми"
    assert "city" not in пусто, "город есть — плашки быть не должно"

    шапка_en, _ = _cover(_проверка("batumi"), lang="en")
    assert шапка_en["city"] == "Batumi"


def test_город_записанный_словами_уезжает_как_записан() -> None:
    шапка, пусто = _cover(_проверка("Батуми"), lang="en")
    assert шапка["city"] == "Батуми"
    assert "city" not in пусто


def test_незнакомый_код_не_теряется() -> None:
    шапка, пусто = _cover(_проверка("zzcity"), lang="ru")
    assert шапка["city"] == "Zzcity"
    assert "city" not in пусто


def test_города_нет_нигде_плашка_горит() -> None:
    шапка, пусто = _cover(_проверка(""), lang="ru")
    assert шапка["city"] == ""
    assert "city" in пусто


def test_прочие_поля_шапки_не_тронуты() -> None:
    detail = _проверка("batumi")
    detail = replace(detail, inspection=replace(detail.inspection, auditor="Иванов"))
    шапка, _ = _cover(detail, lang="ru")
    assert шапка["auditor"] == "Иванов"
