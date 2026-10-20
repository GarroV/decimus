"""Информационная часть загруженной проверки: `import_info_fields`, `import_set_info`.

База подменена: проверяется разбор значений по виду поля (да/нет, дата, текст),
отказ на кривой дате и то, что в базу уходит записываемый вид в порядке методики.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from src.db import imports as db_imports
from src.db.models import ORIGIN_IMPORT, ORIGIN_LEGACY, InfoRow, InspectionDetail, InspectionRow
from src.domain.info_fields import FIELDS
from src.mcp import import_info
from src.mcp.errors import ToolError

ID = "11111111-1111-1111-1111-111111111111"


def _detail(*, lang: str = "ru", info: tuple[InfoRow, ...] = ()) -> InspectionDetail:
    row = InspectionRow(
        id=ID,
        tenant_code="укашка",
        unit_name="Белград-1",
        chat_id=0,
        kind="planned",
        inspection_date=date(2026, 8, 19),
        report_lang=lang,
        checklist_version="v1",
        pct=99.5,
        grade="A",
        findings_count=0,
        pushed_at="2026-08-19T18:00:00+02:00",
        origin=ORIGIN_IMPORT,
    )
    return InspectionDetail(
        inspection=replace(row, on_review=True),
        deductions=0.0,
        counts={},
        by_zone={},
        findings=(),
        info=info,
    )


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Подмена базы и методики; список накапливает то, что ушло бы в `inspection_info`."""
    calls: list[Any] = []
    state = {"detail": _detail(), "origin": ORIGIN_IMPORT}
    monkeypatch.setattr(
        import_info,
        "_only_import",
        lambda *a, **k: (state["detail"], type("Head", (), {"origin": state["origin"]})()),
    )
    monkeypatch.setattr(
        import_info, "_fields_of", lambda detail: tuple((f, f"Вопрос {f.code}") for f in FIELDS)
    )
    monkeypatch.setattr(
        db_imports, "set_info", lambda ident, values, *, tenant: calls.append(list(values))
    )
    calls.append(state)  # нулевой элемент — управление подменой, значения идут дальше
    return calls


def _set(values: dict[str, Any]) -> dict[str, object]:
    return import_info.import_set_info(
        tenant="укашка",
        store=None,  # type: ignore[arg-type]
        actor="mcp:HQ",
        inspection_id=ID,
        values=values,
    )


def test_да_нет_и_дата_записываются_в_виде_отчёта(written: list[Any]) -> None:
    answer = _set({"INF05": "созвон 15.09.2026 14:00", "INF03": "yes", "INF04": "Нет"})

    # Порядок записи — порядок методики, а не порядок аргументов.
    assert written[1] == [
        ("INF03", "Да"),
        ("INF04", "Нет"),
        ("INF05", "15.09.2026 14:00"),
    ]
    assert answer["saved"] == {"INF03": "Да", "INF04": "Нет", "INF05": "15.09.2026 14:00"}


def test_да_нет_на_английском_языке_отчёта(written: list[Any]) -> None:
    written[0]["detail"] = _detail(lang="en")

    _set({"INF03": "no"})

    assert written[1] == [("INF03", "No")]


def test_en_отчёт_принимает_да_и_yes_и_пишет_по_английски(written: list[Any]) -> None:
    written[0]["detail"] = _detail(lang="en")

    _set({"INF03": "да", "INF04": "yes", "INF07": "15 September 2026"})

    assert written[1] == [("INF03", "Yes"), ("INF04", "Yes"), ("INF07", "15.09.2026")]


def test_кривая_дата_отказ_и_ничего_не_записано(written: list[Any]) -> None:
    with pytest.raises(ToolError, match="не дата"):
        _set({"INF03": "yes", "INF07": "завтра после обеда"})

    assert len(written) == 1


def test_не_да_нет_и_чужой_код_отказ(written: list[Any]) -> None:
    with pytest.raises(ToolError, match="да/нет"):
        _set({"INF03": "возможно"})
    with pytest.raises(ToolError, match="нет"):
        _set({"INF99": "x"})

    assert len(written) == 1


def test_историческая_проверка_без_информационной_части(written: list[Any]) -> None:
    written[0]["origin"] = ORIGIN_LEGACY

    with pytest.raises(ToolError, match="историческая"):
        _set({"INF03": "yes"})


def test_чтение_показывает_вид_вопрос_и_недостающее(written: list[Any]) -> None:
    written[0]["detail"] = _detail(info=(InfoRow(code="INF03", text="Да"),))

    answer = import_info.import_info_fields(
        tenant="укашка",
        store=None,  # type: ignore[arg-type]
        actor="mcp:HQ",
        inspection_id=ID,
    )

    fields = {f["code"]: f for f in answer["fields"]}  # type: ignore[attr-defined]
    assert fields["INF03"]["value"] == "Да"
    assert fields["INF05"]["kind"] == "date"
    assert fields["INF05"]["question"] == "Вопрос INF05"
    assert "INF03" not in answer["missing"]  # type: ignore[operator]
    assert "INF01" in answer["missing"]  # type: ignore[operator]
