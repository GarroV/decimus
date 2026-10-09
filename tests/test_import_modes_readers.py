"""Историческая проверка у читателей без базы (D332, D310) — ядро: движок и письмо.

Пересчёт и сверка письма отказывают исторической ДО поиска методики: её
версия (`legacy:<метка>`) в хранилище не лежит, и без заслона отказ звучал бы как
поломка, а с подменой каталога — пересчитал бы оценку старого отчёта. Сводка
сопоставимости держит каждую прежнюю методику своей группой.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.db.models import InspectionDetail, InspectionRow
from src.mcp import methodologies
from src.report import letters, rescore
from src.report.letters import LetterError, Papers


def _строка(
    origin: str, *, version: str = "legacy:Qvalon 133", pct: float = 95.29
) -> InspectionRow:
    return InspectionRow(
        id="00000000-0000-0000-0000-000000000001",
        tenant_code="HQ",
        unit_name="Batumi-1",
        chat_id=0,
        kind="planned",
        inspection_date=date(2024, 3, 15),
        report_lang="ru",
        checklist_version=version,
        pct=pct,
        grade="",
        findings_count=0,
        pushed_at="2026-10-09T00:00:00",
        origin=origin,
    )


def _проверка(origin: str) -> InspectionDetail:
    return InspectionDetail(
        inspection=_строка(origin), deductions=0.0, counts={}, by_zone={}, findings=()
    )


@pytest.fixture
def бумаги_повсюду(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Papers:
    """Методика «находится» для любой версии, а движок падает, если позван.

    Так заслон проверяется честно: без него пересчёт дошёл бы до движка.
    """

    def найдено(_version: str, _papers: Papers) -> tuple[Path, str]:
        return tmp_path, "store"

    def движок(*_a: object, **_k: object) -> tuple[int, str, str]:
        raise AssertionError("движок позван для исторической")

    monkeypatch.setattr(letters, "_methodology", найдено)
    monkeypatch.setattr(letters, "_run", движок)
    return Papers(live=tmp_path, store=None, shelf=None)


def test_пересчёт_исторической_отказ_до_движка(бумаги_повсюду: Papers) -> None:
    with pytest.raises(LetterError, match="историческая"):
        rescore.rescore(_проверка("legacy"), papers=бумаги_повсюду)
    with pytest.raises(LetterError, match="историческая"):
        rescore.apply_command(_проверка("legacy"), papers=бумаги_повсюду, args=["drop", "1"])


@pytest.mark.parametrize("origin", ["legacy", "import"])
def test_письма_по_загруженной_нет(origin: str, бумаги_повсюду: Papers) -> None:
    with pytest.raises(LetterError, match="письма партнёру"):
        letters.build(_проверка(origin), lang=None, papers=бумаги_повсюду)


def test_каждая_прежняя_методика_своя_группа_в_справке() -> None:
    def цена(_version: str, _code: str, _papers: Papers) -> str | None:
        raise AssertionError("цену исторической не читают — методики её нет")

    ряд = [
        _строка("legacy", version="legacy:Qvalon 133"),
        _строка("legacy", version="legacy:Qvalon 133"),
        _строка("legacy", version="legacy:old 253"),
    ]
    справка = methodologies.of(ряд, papers=Papers(live=None, store=None, shelf=None), shape=цена)
    assert [g["inspections"] for g in справка["groups"]] == [2, 1]  # type: ignore[index]
    assert "Historical" in str(справка["note"])
    assert "accepted as true" in str(справка["note"])
