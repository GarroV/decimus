"""Пересчёт записанной проверки движком (D200) — и повтор в состоянии для движка (D191).

Числа здесь — ядро: исправленная запись под буквой, посчитанной по старой
записи, выглядела бы пересчитанной и ушла бы в историю сети как факт.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import mcp_checklist_harness as harness
import pytest
from mcp_checklist_harness import build_edition, build_methodology
from test_mcp_letters import ВЕРСИЯ, _проверка

from src.report import letters
from src.report.letters import LetterError
from src.report.rescore import rescore


@pytest.fixture
def хранилище(tmp_path: Path) -> letters.Papers:
    build_edition(tmp_path / "store" / "versions" / ВЕРСИЯ)
    build_methodology(tmp_path / "live")
    return letters.Papers(live=tmp_path / "live", store=tmp_path / "store")


def test_без_правок_пересчёт_даёт_записанную_оценку(хранилище: letters.Papers) -> None:
    # Arrange — та же проверка, по которой письмо сверяет оценку: 99.5% A.
    проверка = _проверка()

    # Act
    оценка = rescore(проверка, papers=хранилище)

    # Assert
    assert (оценка.pct, оценка.grade) == (99.5, "A")


def test_смена_класса_двигает_оценку(хранилище: letters.Papers) -> None:
    # Arrange
    проверка = _проверка()
    тяжелее = replace(проверка, findings=(replace(проверка.findings[0], level="D2"),))

    # Act
    до, после = rescore(проверка, papers=хранилище), rescore(тяжелее, papers=хранилище)

    # Assert — D2 дороже D1: оценка обязана упасть.
    assert после.pct < до.pct
    assert после.counts.get("D2") == 1


def test_повтор_удваивает_вычет_и_письмо_собирается(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange — методика с множителем повтора 2 (у боевой он такой же). В наборе
    # оснастки множителя нет, то есть 1.0, и повтор там не стоит ничего —
    # на нём этот дефект не виден вовсе.
    monkeypatch.setitem(harness.SCORING, "repeat_multiplier", 2.0)
    черновик = tmp_path / "edition"
    издание = build_edition(черновик)
    (tmp_path / "store" / "versions").mkdir(parents=True)
    shutil.move(str(черновик), str(tmp_path / "store" / "versions" / издание))
    хранилище = letters.Papers(live=None, store=tmp_path / "store")
    основа = _проверка()
    проверка = replace(основа, inspection=replace(основа.inspection, checklist_version=издание))
    с_повтором = replace(проверка, findings=(replace(проверка.findings[0], repeat=True),))

    # Act
    обычная = rescore(проверка, papers=хранилище)
    повторная = rescore(с_повтором, papers=хранилище)
    записанная = replace(
        с_повтором,
        inspection=replace(с_повтором.inspection, pct=повторная.pct, grade=повторная.grade),
    )
    письмо = letters.build(записанная, lang=None, papers=хранилище)

    # Assert — повтор вдвое дороже, и письмо по такой проверке собирается: без
    # повтора в состоянии сверка считала её дешевле записанной и отказывала.
    assert 100 - повторная.pct == pytest.approx(2 * (100 - обычная.pct))
    assert письмо["letter"]


def test_методики_версии_нет_отказ_а_не_прежняя_оценка(tmp_path: Path) -> None:
    with pytest.raises(LetterError):
        rescore(_проверка(), papers=letters.Papers(live=None, store=None))
