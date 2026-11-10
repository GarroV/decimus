"""D740: срок отчёта — третий рабочий день со следующего дня; сб и вс не считаются.

Ядро по правилу «ошибка молчалива»: сбитый срок — правдоподобная дата в календаре человека.
Примеры первых трёх — слова владельца и таблица из задачи #1590.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.domain.report_deadline import event_title, report_due_date


@pytest.mark.parametrize(
    ("checked", "due"),
    [
        (date(2026, 11, 6), date(2026, 11, 11)),  # пятница → среда
        (date(2026, 11, 4), date(2026, 11, 9)),  # среда → понедельник
        (date(2026, 11, 5), date(2026, 11, 10)),  # четверг → вторник
        (date(2026, 11, 2), date(2026, 11, 5)),  # понедельник → четверг, выходных нет
        (date(2026, 11, 3), date(2026, 11, 6)),  # вторник → пятница
        (date(2026, 11, 7), date(2026, 11, 11)),  # суббота: отсчёт с пн → среда
        (date(2026, 11, 8), date(2026, 11, 11)),  # воскресенье: то же
        (date(2026, 12, 30), date(2027, 1, 4)),  # через границу года
        (date(2024, 2, 28), date(2024, 3, 4)),  # високосный февраль: ср → пн
    ],
)
def test_report_due_date(checked: date, due: date) -> None:
    assert report_due_date(checked) == due


def test_срок_никогда_не_выпадает_на_выходной_и_всегда_позже_проверки() -> None:
    начало = date(2026, 1, 1)
    for сдвиг in range(800):
        день = начало + timedelta(days=сдвиг)
        срок = report_due_date(день)
        assert срок.weekday() < 5, (день, срок)
        # Не меньше трёх и не больше пяти календарных дней (3 рабочих + выходные между).
        assert 3 <= (срок - день).days <= 5, (день, срок)


def test_название_на_языке_интерфейса() -> None:
    день = date(2026, 11, 4)
    assert (
        event_title(" Белград-1 ", день, "ru") == "Отправить отчёт по проверке — Белград-1 (04.11)"
    )
    assert (
        event_title("Belgrade-1", день, "en") == "Send the inspection report — Belgrade-1 (04.11)"
    )


def test_неизвестный_язык_даёт_английское_название() -> None:
    assert event_title("X", date(2026, 3, 9), "sr").startswith("Send the inspection report")
