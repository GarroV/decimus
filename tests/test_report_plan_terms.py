"""Сроки строк экшн-плана берутся у движка, а не считаются продуктом (#1168, CLAUDE.md).

Ядро: срок строки партнёр читает как факт. «Сроки — только через `engine/audit.py
score`»: дни записи (дни пункта, не больше потолка класса, D3 — немедленно) отдаёт движок,
а `report.plan_terms` их разбирает. Тесты идут настоящим движком по методике оснастки
и держат два случая, где собственный расчёт разошёлся бы: потолок класса режет дни
пункта, D3 — ноль.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import mcp_checklist_harness as harness
import pytest
from mcp_checklist_harness import build_edition, build_methodology
from test_mcp_letters import ВЕРСИЯ, _проверка

from src.db.errors import ActionPlanError
from src.report import letters
from src.report.plan_terms import _title, finding_terms, provider


def _хранилище(tmp_path: Path) -> letters.Papers:
    build_edition(tmp_path / "store" / "versions" / ВЕРСИЯ)
    build_methodology(tmp_path / "live")
    return letters.Papers(live=tmp_path / "live", store=tmp_path / "store")


def _с_классом(уровень: str) -> object:
    проверка = _проверка()
    return replace(проверка, findings=(replace(проверка.findings[0], level=уровень),))


def test_дни_записи_это_дни_пункта_методики(tmp_path: Path) -> None:
    условия = finding_terms(_проверка(), papers=_хранилище(tmp_path))  # type: ignore[arg-type]

    assert условия[1].days == 10
    assert (условия[1].title_ru, условия[1].title_en) == ("Пол чистый", "Floor is clean")


def test_потолок_класса_режет_дни_пункта_это_решает_движок(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    потолки = dict(harness.SCORING["deadlines"]["max_days"])  # type: ignore[index]
    monkeypatch.setitem(harness.SCORING["deadlines"], "max_days", {**потолки, "D1": 3})  # type: ignore[arg-type]
    черновик = tmp_path / "edition"
    издание = build_edition(черновик)
    (tmp_path / "store" / "versions").mkdir(parents=True)
    shutil.move(str(черновик), str(tmp_path / "store" / "versions" / издание))
    основа = _проверка()
    проверка = replace(основа, inspection=replace(основа.inspection, checklist_version=издание))

    условия = finding_terms(проверка, papers=letters.Papers(live=None, store=tmp_path / "store"))

    assert условия[1].days == 3


def test_d3_немедленно(tmp_path: Path) -> None:
    условия = finding_terms(_с_классом("D3"), papers=_хранилище(tmp_path))  # type: ignore[arg-type]

    assert условия[1].days == 0


def test_поставщик_читает_проверку_и_считает_движок(tmp_path: Path) -> None:
    спрошено: list[str] = []

    def загрузить(ident: str) -> object:
        спрошено.append(ident)
        return _проверка()

    условия = provider(загрузить, papers=_хранилище(tmp_path))("id-проверки")  # type: ignore[arg-type]

    assert спрошено == ["id-проверки"] and условия[1].days == 10


def test_нет_проверки_это_отказ_плана_а_не_пустые_условия(tmp_path: Path) -> None:
    with pytest.raises(ActionPlanError, match="не прочитана"):
        provider(lambda _ident: None, papers=_хранилище(tmp_path))("x")


def test_нет_методики_версии_это_отказ_плана_с_причиной(tmp_path: Path) -> None:
    без_методики = letters.Papers(live=None, store=None)

    with pytest.raises(ActionPlanError, match="от движка не получены"):
        provider(lambda _ident: _проверка(), papers=без_методики)("x")


@pytest.mark.parametrize(
    ("сырое", "строка"),
    [
        ("Стол без пятен (D1)", "Стол без пятен"),
        ("(D1, D2) Заготовка размечена", "Заготовка размечена"),
        ("Пол чистый", "Пол чистый"),
        (None, ""),
    ],
)
def test_класс_в_формулировке_пункта_в_строке_плана_лишний(сырое: str | None, строка: str) -> None:
    assert _title(сырое) == строка
