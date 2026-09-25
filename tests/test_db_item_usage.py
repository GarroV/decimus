"""D197: сводка пункта в панели «Методики» — сколько раз, где и когда нарушен.

Проверяется то, чья ошибка молчит: отклонённая проверка не прибавляет
нарушений (сводку читает и администратор истории, которому она видна),
чужой чек-лист не смешивается со своим, а точки считаются различными.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import requires_db
from db_harness import set_retraction_env

pytest.importorskip("psycopg")

from src.db.push import push_inspection
from src.db.queries import item_usage
from src.db.retract import retract_inspection
from src.domain import add_finding, start_inspection

pytestmark = requires_db


@pytest.fixture
def admin_env(db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    return set_retraction_env(db_env, monkeypatch)


#: Пункт многих зон: одна проверка записывает его по разу в зону — второй раз
#: в той же зоне движок не примет.
ПУНКТ = "CLN03"
ЗОНЫ = ("hot_kitchen", "cold_kitchen", "dough")


def _проверка(chat_id: int, точка: str, записей: int) -> str:
    start_inspection(chat_id, unit=точка, kind="planned", report_lang="ru", tenant="default")
    for зона in ЗОНЫ[:записей]:
        add_finding(chat_id, code=ПУНКТ, level="D1", zone=зона, text="подтёки на стене")
    return push_inspection(chat_id)


def test_сводка_пункта_не_считает_отклонённую(domain_env: Path, admin_env: str) -> None:
    # Arrange — две сданные проверки на двух точках и одна отклонённая.
    _проверка(901, "Белград-1", 2)
    _проверка(902, "Белград-2", 1)
    лишняя = _проверка(903, "Белград-2", 3)
    retract_inspection(лишняя, tenant="default", reason="дубль")

    # Act
    сводка = item_usage(tenant="default", code=ПУНКТ.lower(), checklist="bizdev")

    # Assert
    assert (сводка.records, сводка.units, сводка.inspections) == (3, 2, 2)
    assert сводка.by_level == (("D1", 3),)
    assert [имя for имя, _, _ in сводка.top_units] == ["Белград-1", "Белград-2"]
    assert сводка.last_date is not None


def test_пункт_чужого_чеклиста_не_смешивается(domain_env: Path, db_env: str) -> None:
    # Arrange
    _проверка(904, "Белград-1", 1)

    # Act
    сводка = item_usage(tenant="default", code=ПУНКТ, checklist="rnd")

    # Assert — у чек-листа rnd проверок нет, и сводка пуста, а не общая.
    assert (сводка.records, сводка.units, сводка.last_date) == (0, 0, None)
