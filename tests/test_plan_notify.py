"""Кому уходят уведомления электронного плана — без базы, курсор-двойник (#1168).

Ядро (молчаливая ошибка тут выглядит как чужое событие на экране): запрос, приём, возврат
и вердикты по строкам получает партнёр страны; отправку на согласование и «строка сделана» —
админы УК (пока девелопер страны не учётка); сам действующий себя не уведомляет. Наружу из
приложения не уходит ничего — только строки `notifications`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.db import plan_notify as note

ЗАПРОС = "aaaaaaaa-0000-0000-0000-000000000001"
СТРОКА = "bbbbbbbb-0000-0000-0000-000000000001"
АННА, БОРИС = "11111111-0000-0000-0000-000000000001", "11111111-0000-0000-0000-000000000002"
АДМИН, ГЛАВНЫЙ = "22222222-0000-0000-0000-000000000001", "22222222-0000-0000-0000-000000000002"


class Курсор:
    """Курсор: страна и пиццерия запроса, партнёры страны, админы УК, поиск по логину."""

    def __init__(self, *, страна: str | None = "GE") -> None:
        self.страна = страна
        self.вставки: list[tuple[Any, ...]] = []
        self._ответ: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        if sql.strip().startswith("insert into notifications"):
            self.вставки.append(tuple(params))
            self._ответ = []
        elif "from action_plan_requests r" in sql:
            self._ответ = [(self.страна, "Batumi-1")]
        elif "join space_countries" in sql:
            assert params == (self.страна,), "партнёры ищутся по стране запроса"
            self._ответ = [(АННА,), (БОРИС,)]
        elif "where role = %s" in sql:
            assert params[1] == "HQ", "админы ищутся в пространстве УК"
            self._ответ = {"admin": [(АДМИН,)], "superadmin": [(ГЛАВНЫЙ,)]}[params[0]]
        elif "where login = %s" in sql:
            ключи = {"ge-anna": (АННА,), "hq-admin": (АДМИН,)}
            найден = ключи.get(params[0])
            self._ответ = [найден] if найден else []
        else:
            raise AssertionError(f"неожиданный запрос: {sql}")

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._ответ[0] if self._ответ else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._ответ


def _послать(
    курсор: Курсор, вид: str, *, актёр: str, пространство: str, row: str | None = None
) -> None:
    note.notify_event(
        курсор,  # type: ignore[arg-type]
        вид,
        ЗАПРОС,
        actor=актёр,
        actor_tenant=пространство,
        row_id=row,
    )


@pytest.mark.parametrize(
    "вид",
    [
        note.KIND_REQUESTED,
        note.KIND_ACCEPTED,
        note.KIND_RETURNED,
        note.KIND_ROW_CONFIRMED,
        note.KIND_ROW_RETURNED,
    ],
)
def test_ответы_и_запрос_получают_партнёры_страны(вид: str) -> None:
    курсор = Курсор()

    _послать(курсор, вид, актёр="hq-admin", пространство="HQ")

    assert [(в[0], в[1]) for в in курсор.вставки] == [(АННА, вид), (БОРИС, вид)]
    assert {в[2] for в in курсор.вставки} == {f"/actions?tab=plans&id={ЗАПРОС}"}
    assert json.loads(курсор.вставки[0][3]) == {"unit": "Batumi-1", "by": "hq-admin"}


@pytest.mark.parametrize("вид", [note.KIND_SUBMITTED, note.KIND_ROW_DONE])
def test_отправку_и_сданную_строку_получают_админы_ук_а_не_партнёр(вид: str) -> None:
    курсор = Курсор()

    _послать(курсор, вид, актёр="ge-anna", пространство="GE", row=СТРОКА)

    assert sorted(в[0] for в in курсор.вставки) == sorted([АДМИН, ГЛАВНЫЙ])
    assert АННА not in {в[0] for в in курсор.вставки}
    assert {в[2] for в in курсор.вставки} == {f"/actions?tab=plans&id={ЗАПРОС}&row={СТРОКА}"}


def test_актёр_сам_себя_не_уведомляет() -> None:
    курсор = Курсор()

    _послать(курсор, note.KIND_ACCEPTED, актёр="ge-anna", пространство="GE")

    assert [в[0] for в in курсор.вставки] == [БОРИС]


def test_у_точки_нет_страны_партнёру_адресовать_некому() -> None:
    курсор = Курсор(страна=None)

    _послать(курсор, note.KIND_ACCEPTED, актёр="hq-admin", пространство="HQ")

    assert курсор.вставки == []
