"""Самопроверки партнёров не в статистике УК: сверка по тексту запросов, без базы (#1532).

D024: самопроверки партнёра в рейтинг УК не идут; D144: сводная аналитика — по
эталону; владелец 07.11.2026: самостоятельные проверки партнёров внутренние и в общую
статистику не попадают. Читает УК — условие `COUNTED_SQL` режет принятые проверки чужих
пространств; партнёр читает страну целиком (D289).

Забытый запрос статистики молчит плавной цифрой, а не ошибкой, поэтому перечень
запросов, где условие обязано стоять, — здесь явно, а не «все, что похоже».
"""

from __future__ import annotations

import pytest

from src.db import (
    inspection_timeline,
    quality_read,
    queries,
    swarm_read,
    unit_scores,
)
from src.db.reach import COUNTED_SQL, Reach, reach_of

#: Запросы, считающие или перечисляющие проверки для статистики, списков и истории точки УК.
СТАТИСТИКА = {
    queries: [
        "_LIST_ALL_TEMPLATE",
        "_LIST_BY_UNIT_TEMPLATE",
        "_FINDINGS_BY_UNIT_SQL",
        "_PROCESS_LOSSES_SQL",
        "_SYSTEMIC_SQL",
        "_SLICE_SUMMARY_SQL",
        "_COUNTRY_SUMMARY_SQL",
        "_CLASS_COUNTS_SQL",
        "_UNIT_LAST_INSPECTIONS_SQL",
        "_WORST_PROCESSES_SQL",
        "_ITEM_RECORDS",
    ],
    swarm_read: ["_INSPECTIONS_SQL", "_FINDING_COUNTS_SQL", "_INSPECTION_COUNTS_SQL"],
    quality_read: ["_AUDIT_SQL"],
    unit_scores: ["_RECENT_SQL"],
    inspection_timeline: ["_SQL", "_DAYS_SQL"],
}


def _текст(модуль: object, имя: str) -> str:
    return " ".join(str(getattr(модуль, имя)).split())


@pytest.mark.parametrize(
    ("модуль", "имя"), [(м, и) for м, имена in СТАТИСТИКА.items() for и in имена]
)
def test_запрос_статистики_не_считает_самопроверки_партнёров(модуль: object, имя: str) -> None:
    assert COUNTED_SQL in _текст(модуль, имя), (
        f"{модуль.__name__}.{имя}: нет условия COUNTED_SQL — принятые проверки партнёров "
        f"попадут в статистику УК"
    )


def test_предыдущая_проверка_в_сводке_тоже_без_самопроверок() -> None:
    """Движение «к прошлой проверке» не должно сравнивать с самопроверкой партнёра."""
    assert "p.tenant_code = 'HQ' or p.status <> 'finalized'" in _текст(
        swarm_read, "_INSPECTIONS_SQL"
    )


def test_читающий_передаётся_в_запрос_параметром() -> None:
    assert reach_of("HQ").params()["reader"] == "HQ"
    assert Reach(tenant="GE", tenants=None, countries=("GE",)).params()["reader"] == "GE"


def test_условие_пропускает_партнёру_всё_а_уК_только_свои_принятые() -> None:
    """Смысл условия, без базы: читает не УК — не режет, ждущие не режет."""
    assert "%(reader)s::text <> 'HQ'" in COUNTED_SQL
    assert "i.tenant_code = 'HQ'" in COUNTED_SQL
    assert "i.status <> 'finalized'" in COUNTED_SQL
