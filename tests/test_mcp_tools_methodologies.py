"""Справка о методиках видна в ответе инструмента и ничего не запрещает (D352).

Расчёт групп — в `test_mcp_methodologies.py`; здесь — что поле есть в ответе,
что фраза в нём не зовёт агента отказываться от средних, и что строку
состояния справка не засоряет: это не предупреждение.

База здесь не нужна и не используется: подменяется слой чтения строк.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.db.models import InspectionRow
from src.mcp import methodologies, tools

ЦЕНА_ПЕРВАЯ = "aaaaaaaaaaaa"
ЦЕНА_ВТОРАЯ = "bbbbbbbbbbbb"


def _проверка(*, version: str, code: str = "bizdev", pct: float = 97.0) -> InspectionRow:
    return InspectionRow(
        id=f"{int(pct * 100):032d}",
        tenant_code="укашка",
        unit_name="Белград-1",
        chat_id=100500,
        kind="planned",
        inspection_date=date(2026, 9, 23),
        report_lang="ru",
        checklist_version=version,
        pct=pct,
        grade="A",
        findings_count=1,
        pushed_at="2026-09-23T18:00:00+02:00",
        checklist_code=code,
    )


@pytest.fixture
def ряд_из_двух_цен(monkeypatch: pytest.MonkeyPatch) -> list[InspectionRow]:
    """Две проверки одного чек-листа, посчитанные по разным ставкам."""
    строки = [
        _проверка(version="набор-2026-09-01-111111111111", pct=97.0),
        _проверка(version="набор-2026-09-10-222222222222", pct=91.0),
    ]
    цены = {
        "набор-2026-09-01-111111111111": ЦЕНА_ПЕРВАЯ,
        "набор-2026-09-10-222222222222": ЦЕНА_ВТОРАЯ,
    }
    monkeypatch.setattr(methodologies, "shape_of", lambda version, code, papers: цены.get(version))
    monkeypatch.setattr(
        tools, "_read", lambda **_: tools._Page(rows=tuple(строки), limit=50, truncated=False)
    )
    monkeypatch.setattr(
        tools,
        "_read_everything",
        lambda **_: tools._Page(rows=tuple(строки), limit=50, truncated=False),
    )
    return строки


def _справка(ответ: dict[str, Any]) -> dict[str, Any]:
    значение = ответ[methodologies.FIELD]
    assert isinstance(значение, dict)
    return значение


@pytest.mark.parametrize(
    "вызов",
    [
        lambda: tools.unit_history(tenant="укашка", unit="Белград-1"),
        lambda: tools.network_summary(tenant="укашка"),
        lambda: tools.list_inspections(tenant="укашка"),
    ],
    ids=["unit_history", "network_summary", "list_inspections"],
)
@pytest.mark.usefixtures("ряд_из_двух_цен")
def test_ряд_двух_методик_справка_а_не_запрет(вызов: Any) -> None:
    """D352: две методики в ряду — справка с двумя группами, средние законны."""
    ответ = вызов()

    справка = _справка(ответ)
    assert len(справка["groups"]) == 2
    assert "comparable" not in справка
    assert "valid" in справка["note"]
    assert "comparability" not in ответ
    assert справка["note"] not in str(ответ["status"]), "справка — не предупреждение в status"


def test_ряд_одной_методики_без_фразы(monkeypatch: pytest.MonkeyPatch) -> None:
    строки = [
        _проверка(version="набор-2026-09-01-111111111111", pct=97.0),
        _проверка(version="набор-2026-09-10-222222222222", pct=91.0),
    ]
    monkeypatch.setattr(methodologies, "shape_of", lambda version, code, papers: ЦЕНА_ПЕРВАЯ)
    monkeypatch.setattr(
        tools, "_read", lambda **_: tools._Page(rows=tuple(строки), limit=50, truncated=False)
    )

    ответ = tools.unit_history(tenant="укашка", unit="Белград-1")

    assert len(_справка(ответ)["groups"]) == 1
    assert _справка(ответ)["note"] == ""
