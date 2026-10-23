"""Ядро электронного плана без базы: состояния, просрочка строки, готовность к отправке (#1168).

«Просрочено» не хранится, а считается на чтении: ошибка здесь — правдоподобно неверная
пометка у партнёра («вы просрочили»), поэтому правила чистыми функциями и с тестами.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.db.action_plans import (
    STATE_CLOSED,
    STATE_IN_WORK,
    STATE_ON_REVIEW,
    STATE_REQUESTED,
    STATE_RETURNED,
    is_overdue,
    plan_state,
)
from src.db.plan_rows import (
    ROW_CONFIRMED,
    ROW_DONE,
    ROW_FILLING,
    ROW_IN_WORK,
    ROW_RETURNED,
    PlanRow,
    row_overdue,
)

СРОК = date(2026, 10, 11)


def _строка(**kw: object) -> PlanRow:
    данные: dict[str, object] = {
        "id": "r1",
        "request_id": "q1",
        "finding_id": "f1",
        "position": 1,
        "item_code": "PRD01",
        "level": "D2",
        "zone": "fridge",
        "title_ru": "Заготовка размечена",
        "title_en": "Prep item is tagged",
        "days": 5,
        "measure": "",
        "responsible": "",
        "reason": "",
        "own_due": None,
        "extended_due": None,
        "due_on": СРОК,
        "status": ROW_FILLING,
        "return_reason": "",
        "updated_at": datetime(2026, 10, 1, tzinfo=UTC),
    }
    данные.update(kw)
    return PlanRow(**данные)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("статус", "сегодня", "просрочена"),
    [
        (ROW_FILLING, date(2026, 10, 12), True),
        (ROW_IN_WORK, date(2026, 10, 12), True),
        (ROW_RETURNED, date(2026, 10, 12), True),
        (ROW_IN_WORK, СРОК, False),
        (ROW_IN_WORK, date(2026, 10, 1), False),
        # Сданная ждёт УК, подтверждённая закончена: партнёру их не вменяют.
        (ROW_DONE, date(2026, 10, 30), False),
        (ROW_CONFIRMED, date(2026, 10, 30), False),
    ],
)
def test_строка_просрочена_пока_её_не_сдал_партнёр(
    статус: str, сегодня: date, просрочена: bool
) -> None:
    assert row_overdue(статус, СРОК, today=сегодня) is просрочена
    assert _строка(status=статус).overdue(сегодня) is просрочена


def test_строка_готова_к_отправке_когда_есть_мера_и_ответственный() -> None:
    assert not _строка().is_filled
    assert not _строка(measure="Заменить", responsible="  ").is_filled
    assert not _строка(measure="  ", responsible="Иванов").is_filled
    assert _строка(measure="Заменить", responsible="Иванов").is_filled


def test_формулировка_на_языке_с_откатом_на_другой_и_на_код() -> None:
    assert _строка().title("ru") == "Заготовка размечена"
    assert _строка().title("en") == "Prep item is tagged"
    assert _строка(title_en="").title("en") == "Заготовка размечена"
    assert _строка(title_ru="", title_en="").title("ru") == "PRD01"


@pytest.mark.parametrize(
    ("статус", "возвращён", "состояние"),
    [
        ("requested", False, STATE_REQUESTED),
        ("requested", True, STATE_RETURNED),
        ("on_review", False, STATE_ON_REVIEW),
        ("in_work", False, STATE_IN_WORK),
        ("closed", False, STATE_CLOSED),
    ],
)
def test_состояние_электронного_плана(статус: str, возвращён: bool, состояние: str) -> None:
    assert plan_state(статус, None, returned=возвращён) == состояние


@pytest.mark.parametrize("статус", ["in_work", "closed"])
def test_план_в_работе_и_закрытый_не_просрочены_как_ответ_планом(статус: str) -> None:
    """Срок ответа планом уже наступил и прошёл: строки считаются отдельно, по своим срокам."""
    assert is_overdue(статус, СРОК, today=date(2026, 12, 1)) is False
