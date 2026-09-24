"""Зона вне списка пункта: человеку можно, машине нельзя (D177 поверх T271).

D177: зона — там, где продукт; названную человеком зону движок принимает и
помечает `zone_unusual`. T271 остаётся для зоны, выведенной машиной: именно она
положила пункт про печь в холодный цех. Пара взята из
`tests/test_bot_zone_unusual.py`: пункт живёт только в горячем цехе.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain import add_finding, edit_finding, get_state, score, start_inspection
from src.domain.errors import EngineError

CHAT = 7001
ПУНКТ = "CLN05"
ЧУЖАЯ = "dining"


def начать() -> None:
    start_inspection(CHAT, "Белград 2", "planned", "ru")


def test_машинная_зона_вне_списка_отклоняется(domain_env: Path) -> None:
    начать()
    with pytest.raises(EngineError):
        add_finding(CHAT, ПУНКТ, "D1", ЧУЖАЯ, "нагар")


def test_зона_человека_вне_списка_принимается_с_пометкой(domain_env: Path) -> None:
    начать()
    finding = add_finding(CHAT, ПУНКТ, "D1", ЧУЖАЯ, "нагар", zone_by_person=True)

    assert (finding.zone, finding.zone_unusual) == (ЧУЖАЯ, True)
    assert score(CHAT).pct == 99.5, "вычет D1 не посчитан для записи в нетипичной зоне"


def test_правка_класса_не_требует_заново_подтверждать_нетипичную_зону(domain_env: Path) -> None:
    """Зона уже стоит по слову человека — правка текста её не отвергает."""
    начать()
    add_finding(CHAT, ПУНКТ, "D1", ЧУЖАЯ, "нагар", zone_by_person=True)

    edit_finding(CHAT, 1, text="нагар на поду")

    state = get_state(CHAT)
    assert state is not None
    finding = state.finding(1)
    assert finding is not None and (finding.zone, finding.zone_unusual) == (ЧУЖАЯ, True)


def test_машинная_правка_в_зону_вне_списка_отклоняется(domain_env: Path) -> None:
    начать()
    add_finding(CHAT, ПУНКТ, "D1", "hot_kitchen", "нагар")
    with pytest.raises(EngineError):
        edit_finding(CHAT, 1, zone=ЧУЖАЯ)
