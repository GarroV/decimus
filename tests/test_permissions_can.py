"""Ядро прав: граница пространств и охват «свои/все» (спека «Администрирование», D304, D306, D311).

Ядро (права доступа) — тестами вперёд. Граница не настраивается: никакое
право не даёт стране тронуть объект УК, чужую страну или действие «только УК».
«Свои» — только проверка, которую занесла учётка этого человека.
"""

from __future__ import annotations

import pytest

from src.domain.permissions import (
    ACTION_CODES,
    HQ_ONLY_ACTIONS,
    INSPECTION_OBJECT_ACTIONS,
    REACH_ALL,
    REACH_OWN,
    RULE_FOREIGN_SPACE,
    RULE_HQ_OBJECT,
    RULE_HQ_ONLY,
    RULE_MATRIX,
    RULE_NOT_AUTHOR,
    RULE_OK,
    Actor,
    UnknownAction,
    can,
    require_action,
)

ВСЁ = {код: REACH_ALL for код in ACTION_CODES}


def уК(grants: dict[str, str] = ВСЁ, tenant: str = "HQ") -> Actor:
    return Actor(tenant=tenant, role="hq_admin", grants=grants, user_id="u-hq")


def страна(tenant: str = "GE", grants: dict[str, str] = ВСЁ) -> Actor:
    return Actor(tenant=tenant, role="country_admin", grants=grants, user_id="u-ge")


def test_каталог_ровно_по_спеке_и_два_кода_расхождений() -> None:
    assert ACTION_CODES == {
        "inspection.conduct",
        "inspection.retract",
        "inspection.move",
        "inspection.accept",
        "inspection.revise",
        "inspection.letter",
        "prescription.manage",
        "prescription.reply",
        "plan.manage",
        "plan.submit",
        "checklist.edit",
        "checklist.publish",
        "checklist.manage",
        "phrases.manage",
        "people.manage",
        "mcp.connect",
        "unit.create",
        "space.manage",
        "roles.manage",
    }


def test_только_уК_ровно_три_действия() -> None:
    assert HQ_ONLY_ACTIONS == {"unit.create", "space.manage", "roles.manage"}


def test_действия_над_проверкой_ровно_пять() -> None:
    assert INSPECTION_OBJECT_ACTIONS == {
        "inspection.retract",
        "inspection.move",
        "inspection.accept",
        "inspection.revise",
        "inspection.letter",
    }


def test_уК_действует_в_пространстве_партнёра() -> None:
    решение = can(уК(), "inspection.retract", "GE", object_author=None)
    assert решение.allowed and решение.rule == RULE_OK


def test_страна_не_трогает_объект_уК_даже_с_правом() -> None:
    решение = can(страна(), "checklist.edit", "HQ")
    assert not решение.allowed and решение.rule == RULE_HQ_OBJECT


def test_страна_не_трогает_чужую_страну() -> None:
    решение = can(страна("GE"), "inspection.retract", "AM", object_author="u-ge")
    assert not решение.allowed and решение.rule == RULE_FOREIGN_SPACE


@pytest.mark.parametrize("код", sorted(HQ_ONLY_ACTIONS))
def test_действие_только_уК_стране_не_даёт_никакое_право(код: str) -> None:
    решение = can(страна(), код, "GE")
    assert not решение.allowed and решение.rule == RULE_HQ_ONLY


def test_без_права_отказ_матрицы_и_у_уК() -> None:
    решение = can(уК(grants={}), "inspection.retract", "HQ", object_author="u-hq")
    assert not решение.allowed and решение.rule == RULE_MATRIX


@pytest.mark.parametrize(
    ("автор", "можно", "правило"),
    [("u-hq", True, RULE_OK), ("u-other", False, RULE_NOT_AUTHOR), (None, False, RULE_NOT_AUTHOR)],
)
def test_охват_свои_только_для_своей_проверки(автор: str | None, можно: bool, правило: str) -> None:
    человек = уК(grants={"inspection.retract": REACH_OWN})
    решение = can(человек, "inspection.retract", "HQ", object_author=автор)
    assert (решение.allowed, решение.rule) == (можно, правило)


def test_свои_без_учётки_не_совпадают_с_пустым_автором() -> None:
    человек = Actor(tenant="HQ", role="hq_staff", grants={"inspection.move": REACH_OWN})
    assert not can(человек, "inspection.move", "HQ", object_author="")


def test_пустая_учётка_не_совпадает_с_пустым_автором() -> None:
    человек = Actor(tenant="HQ", role="hq_staff", grants={"inspection.move": REACH_OWN}, user_id="")
    assert not can(человек, "inspection.move", "HQ", object_author="")


def test_действие_над_проверкой_без_автора_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="автор"):
        can(уК(), "inspection.retract", "HQ")


def test_неизвестный_охват_это_отказ_матрицы() -> None:
    решение = can(уК(grants={"checklist.edit": "some"}), "checklist.edit", "HQ")
    assert not решение.allowed and решение.rule == RULE_MATRIX


def test_старый_код_уК_приводится() -> None:
    assert can(уК(tenant="default"), "unit.create", "HQ").allowed


def test_неизвестное_действие_это_ошибка_кода() -> None:
    with pytest.raises(UnknownAction, match=r"inspection\.delete"):
        can(уК(), "inspection.delete", "HQ")


def test_действие_каталога_находится_по_коду() -> None:
    assert require_action("inspection.move").on_inspection
    assert require_action("unit.create").hq_only
    with pytest.raises(UnknownAction, match=r"inspection\.delete"):
        require_action("inspection.delete")


def test_пустое_пространство_объекта_это_ошибка_кода() -> None:
    with pytest.raises(ValueError, match="пространство"):
        can(уК(), "checklist.edit", "  ")


def test_отказ_ложен_в_условии() -> None:
    assert not can(страна(), "checklist.edit", "HQ")
