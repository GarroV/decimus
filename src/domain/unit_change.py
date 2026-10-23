"""Сменить пиццерию начатой проверки (D628).

Аудитор завёл проверку не на ту точку — опечатка, соседняя пиццерия того же города.
Начинать заново значило бы потерять записанное, поэтому меняется только шапка:
записи, кадры и оценка остаются. Правит шапку сам движок (`meta --unit`), блок
второй копии имени не держит — как и у языка отчёта (`state.set_report_lang`).

Пометки повтора (D191, D255) аудитор ставил ответом на вопрос, заданный по прошлой
проверке ПРЕЖНЕЙ точки, и сами они не снимаются: решение было человека. Поэтому бот
после смены называет, сколько таких записей, — перепроверить их должен он же.
"""

from __future__ import annotations

from .config import check_environment
from .engine import option, run_audit, state_file
from .errors import DomainError, InspectionNotStarted, ValidationError
from .models import Inspection
from .state import read_state, settings_for


def set_unit(chat_id: int, unit: str) -> Inspection:
    """Назначить начатой проверке другую пиццерию. Имя — уже сверенное со справочником.

    Та же пиццерия — отказ: менять нечего, а молчаливый «успех» спрятал бы опечатку
    в вызывающем коде.
    """
    from .handover import guard_writable  # handover сам читает `state_lock` из state

    guard_writable(chat_id)
    имя = unit.strip()
    if not имя:
        raise ValidationError("Пиццерия не названа — менять не на что")
    settings = check_environment()
    current = read_state(chat_id, settings)
    if current is None:
        raise InspectionNotStarted(
            f"В этом чате проверка не начата — нет {state_file(chat_id, settings)}. "
            f"Пиццерию менять некому"
        )
    if current.unit == имя:
        raise ValidationError(f"Проверка уже заведена на «{имя}»")
    run_audit(["meta", option("unit", имя)], chat_id=chat_id, settings=settings_for(chat_id))
    updated = read_state(chat_id, settings)
    if updated is None:
        raise DomainError(
            f"Движок отчитался об успехе, но состояния нет: {state_file(chat_id, settings)}"
        )
    return updated
