"""`can` — граница пространств (слой 1) и короткие вопросы к матрице."""

from __future__ import annotations

import pytest

from src.domain import permissions as perm
from src.domain.permissions import Actor, can

АДМИН_УК = Actor(tenant="HQ", role="admin")
ДЕВЕЛОПЕР = Actor(tenant="HQ", role="developer")
АДМИН_RS = Actor(tenant="RS", role="admin")
СОТРУДНИК_RS = Actor(tenant="RS", role="auditor")


def _правило(кто: Actor, код: str, чьё: str | None = None) -> tuple[bool, str]:
    решение = can(кто, код, чьё)
    return решение.allowed, решение.rule


def test_УК_действует_у_партнёра_если_действие_не_только_своё() -> None:
    assert _правило(АДМИН_УК, "checklist.edit", "RS") == (True, perm.RULE_OK)


def test_проверки_и_письма_УК_только_в_своём_пространстве() -> None:
    """D283, D341: правка, снятие, перенос, приёмка и письмо — по своей проверке.

    Открыть УК запись в проверки партнёров (D406) — отдельный шаг вместе с
    журналом действий; пока граница держит своё пространство и у УК.
    """
    for код in (
        "inspection.accept",
        "inspection.revise",
        "inspection.retract",
        "inspection.move",
        "inspection.letter",
    ):
        assert _правило(ДЕВЕЛОПЕР, код, "RS") == (False, perm.RULE_FOREIGN_SPACE), код
        assert _правило(ДЕВЕЛОПЕР, код, "HQ") == (True, perm.RULE_OK), код


def test_партнёр_не_трогает_объект_УК_и_чужую_страну() -> None:
    assert _правило(АДМИН_RS, "checklist.edit", "HQ") == (False, perm.RULE_HQ_OBJECT)
    assert _правило(АДМИН_RS, "checklist.edit", "GE") == (False, perm.RULE_FOREIGN_SPACE)
    assert _правило(АДМИН_RS, "checklist.edit", "RS") == (True, perm.RULE_OK)


def test_только_УК_и_только_партнёр() -> None:
    assert _правило(АДМИН_RS, "unit.create") == (False, perm.RULE_HQ_ONLY)
    assert _правило(АДМИН_УК, "plan.submit") == (False, perm.RULE_PARTNER_ONLY)
    assert _правило(СОТРУДНИК_RS, "plan.submit") == (True, perm.RULE_OK)


def test_незнакомая_роль_и_роль_не_своей_стороны_закрыты() -> None:
    assert _правило(Actor(tenant="HQ", role="auditor"), "inspection.read") == (
        False,
        perm.RULE_UNKNOWN_ROLE,
    )
    assert _правило(Actor(tenant="RS", role="developer"), "inspection.read") == (
        False,
        perm.RULE_UNKNOWN_ROLE,
    )
    assert _правило(Actor(tenant="HQ", role=None), "inspection.read") == (
        False,
        perm.RULE_UNKNOWN_ROLE,
    )


def test_старый_код_УК_переводится() -> None:
    assert can(Actor(tenant="default", role="admin"), "unit.create").allowed


def test_незнакомое_действие_и_пустое_пространство_ошибка_кода() -> None:
    with pytest.raises(perm.UnknownAction, match=r"inspection\.telepathy"):
        can(АДМИН_УК, "inspection.telepathy")
    with pytest.raises(ValueError, match="пространство"):
        can(Actor(tenant="", role="admin"), "inspection.read")
    with pytest.raises(ValueError, match="пространство"):
        can(АДМИН_УК, "inspection.read", " ")


def test_role_may_без_пространства_отказ() -> None:
    assert perm.role_may("admin", None, "inspection.read") is False
    with pytest.raises(perm.UnknownAction):
        perm.role_may("admin", None, "nope.nope")


def test_claude_снятие_закрыто_всем_методика_партнёру() -> None:
    """D341, D417: снятия в Claude нет ни у кого; партнёр в Claude методику не видит."""
    assert perm.role_may("superadmin", "HQ", "inspection.retract")
    assert not perm.claude_may("superadmin", "HQ", "inspection.retract")
    assert perm.role_may("admin", "RS", "checklist.edit")
    assert not perm.claude_may("admin", "RS", "checklist.edit")
    assert not perm.claude_may("auditor", "RS", "checklist.read")
    assert perm.claude_may("developer", "HQ", "checklist.edit")
    assert perm.claude_may("auditor", "RS", "inspection.read")


def test_только_чтение_у_гостя() -> None:
    assert perm.is_read_only("guest", "HQ")
    assert not perm.is_read_only("control", "HQ")
    assert not perm.is_read_only("auditor", "RS")
    assert perm.is_read_only("nobody", "HQ")
    assert perm.is_read_only("admin", None)


def test_граница_без_роли() -> None:
    assert perm.open_to_space("unit.create", "HQ")
    assert not perm.open_to_space("unit.create", "RS")


def test_код_раздела() -> None:
    assert perm.view_code("registry") == "view.registry"
    with pytest.raises(perm.UnknownAction):
        perm.view_code("nowhere")
