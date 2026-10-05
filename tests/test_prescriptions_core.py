"""Предписания: чистые правила — просрочка, состояние, адресаты, черновик (волна 3).

«Просрочено» не хранится, а считается (спека, жизненный цикл): ошибка здесь
молчаливая — экран покажет «действует» там, где срок давно прошёл.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.db import prescriptions as rx
from src.db.errors import PrescriptionError

СРОК = date(2026, 10, 10)


@pytest.mark.parametrize(
    ("status", "сегодня", "ожидание"),
    [
        ("issued", date(2026, 10, 11), True),
        ("issued", date(2026, 10, 10), False),
        ("issued", date(2026, 10, 1), False),
        ("draft", date(2026, 12, 1), False),
        ("closed", date(2026, 12, 1), False),
    ],
)
def test_просрочено_только_действующее_после_срока(
    status: str, сегодня: date, ожидание: bool
) -> None:
    assert rx.is_overdue(status, СРОК, today=сегодня) is ожидание


def test_неизвестный_статус_это_отказ_а_не_ложь() -> None:
    with pytest.raises(PrescriptionError, match="неизвестен"):
        rx.is_overdue("sent", СРОК, today=СРОК)


@pytest.mark.parametrize(
    ("status", "сегодня", "состояние"),
    [
        ("draft", date(2026, 12, 1), rx.STATE_DRAFT),
        ("issued", date(2026, 10, 9), rx.STATE_ACTIVE),
        ("issued", date(2026, 10, 11), rx.STATE_OVERDUE),
        ("closed", date(2026, 10, 11), rx.STATE_CLOSED),
    ],
)
def test_состояние_для_экрана(status: str, сегодня: date, состояние: str) -> None:
    assert rx.state_of(status, СРОК, today=сегодня) == состояние


def test_адресаты_разбираются_и_повтор_выпадает() -> None:
    сырьё = "ops@ge.example.com; Boss@ge.example.com\nops@GE.example.com, "
    assert rx.parse_recipients(сырьё) == "ops@ge.example.com, Boss@ge.example.com"


@pytest.mark.parametrize("кривой", ["ops", "ops@", "a b@x.ge", "Имя <ops@x.ge>"])
def test_кривой_адрес_это_отказ(кривой: str) -> None:
    with pytest.raises(PrescriptionError, match="не похоже на адрес"):
        rx.parse_recipients(кривой)


def _черновик(**поля: object) -> rx.Draft:
    основа: dict[str, object] = {
        "country": "GE",
        "due_on": date(2026, 10, 20),
        "recipients": "ops@ge.example.com",
        "subject": " Предписание ",
        "body": " текст ",
    }
    return rx.Draft(**{**основа, **поля})  # type: ignore[arg-type]


def test_черновик_приводится_к_виду_базы() -> None:
    чистый = rx.check_draft(
        _черновик(unit_ids=("11111111-1111-1111-1111-111111111111",) * 2), on=date(2026, 10, 5)
    )
    assert (чистый.subject, чистый.body) == ("Предписание", "текст")
    assert чистый.unit_ids == ("11111111-1111-1111-1111-111111111111",)


@pytest.mark.parametrize(
    ("поля", "причина"),
    [
        ({"country": ""}, "Страна не выбрана"),
        ({"subject": "  "}, "Нет темы"),
        ({"body": ""}, "Нет текста"),
        ({"due_on": date(2026, 10, 4)}, "уже прошёл"),
        ({"unit_ids": ("../etc",)}, "не разобран"),
        ({"inspection_ids": ("1 or 1=1",)}, "не разобран"),
    ],
)
def test_неполный_черновик_это_отказ(поля: dict[str, object], причина: str) -> None:
    with pytest.raises(PrescriptionError, match=причина):
        rx.check_draft(_черновик(**поля), on=date(2026, 10, 5))
