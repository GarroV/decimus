"""#585 (D362, D364): кто кого ведёт на экране «Пользователи» — правило, без экрана и базы.

Права — ядро: ошибка здесь не кричит, она молча раздаёт админов или показывает
чужие логины и почты. Поэтому правило проверяется отдельно от маршрутов,
таблицей «кто → над кем → что можно», а маршруты (`test_web_users_scope.py`)
проверяют, что зовут именно его.

Роли партнёра (D346) — те же коды, что в УК: админ пространства — `admin`,
сотрудник — `auditor`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.web.access_policy import (
    CONTROL,
    HQ_ADMIN,
    PARTNER_ADMIN,
    SUPER,
    grantable_roles,
    manages_spaces,
    may_grant,
    may_touch,
    scope_of,
    spaces_for_add,
    visible,
)


def строка(login: str, tenant: str, role: str) -> Any:
    return SimpleNamespace(login=login, tenant=tenant, role=role)


ВСЕ = (
    строка("boss", "HQ", "superadmin"),
    строка("dev", "HQ", "admin"),
    строка("vika", "HQ", "control"),
    строка("petr", "HQ", "auditor"),
    строка("nino", "GE", "admin"),
    строка("gia", "GE", "auditor"),
    строка("ani", "AM", "admin"),
    строка("aram", "AM", "auditor"),
)


@pytest.mark.parametrize(
    ("role", "tenant", "kind"),
    [
        ("superadmin", "HQ", SUPER),
        ("admin", "HQ", HQ_ADMIN),
        ("admin", "default", HQ_ADMIN),
        ("control", "HQ", CONTROL),
        ("admin", "GE", PARTNER_ADMIN),
        ("auditor", "HQ", None),
        ("auditor", "GE", None),
        # Главный админ и контроль вне УК не бывают (схема), но правило не верит
        # схеме на слово: такая учётка не ведёт никого.
        ("superadmin", "GE", None),
        ("control", "GE", None),
        (None, "HQ", None),
        ("", "", None),
    ],
)
def test_охват_по_роли_и_пространству(role: Any, tenant: str, kind: str | None) -> None:
    охват = scope_of(role, tenant)
    assert (охват.kind if охват else None) == kind


def _видит(role: str, tenant: str) -> set[str]:
    охват = scope_of(role, tenant)
    assert охват is not None
    return {r.login for r in visible(охват, ВСЕ)}


def test_главный_админ_видит_всех() -> None:
    assert _видит("superadmin", "HQ") == {r.login for r in ВСЕ}


def test_админ_уК_видит_уК_без_админов_и_всех_партнёров() -> None:
    assert _видит("admin", "HQ") == {"vika", "petr", "nino", "gia", "ani", "aram"}


def test_контроль_видит_только_контроль() -> None:
    assert _видит("control", "HQ") == {"vika"}


def test_админ_партнёра_видит_только_своё_пространство() -> None:
    assert _видит("admin", "GE") == {"nino", "gia"}
    assert _видит("admin", "AM") == {"ani", "aram"}


ЦЕЛИ = [(r.tenant, r.role) for r in ВСЕ]

#: Кого вошедший может трогать (отключить, почта, роль): (пространство, роль цели).
ТРОГАЕТ: dict[tuple[str, str], set[tuple[str, str]]] = {
    ("superadmin", "HQ"): set(ЦЕЛИ),
    ("admin", "HQ"): {
        ("HQ", "control"),
        ("HQ", "auditor"),
        ("GE", "admin"),
        ("GE", "auditor"),
        ("AM", "admin"),
        ("AM", "auditor"),
    },
    ("control", "HQ"): {("HQ", "control")},
    ("admin", "GE"): {("GE", "admin"), ("GE", "auditor")},
}


@pytest.mark.parametrize("кто", list(ТРОГАЕТ))
@pytest.mark.parametrize("цель", ЦЕЛИ)
def test_кого_можно_трогать(кто: tuple[str, str], цель: tuple[str, str]) -> None:
    охват = scope_of(*кто)
    assert охват is not None
    assert may_touch(охват, tenant=цель[0], role=цель[1]) is (цель in ТРОГАЕТ[кто])


#: Какие роли вошедший может ВЫДАТЬ в пространстве (заведение и смена роли).
ВЫДАЁТ: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {
    ("superadmin", "HQ"): {
        "HQ": ("auditor", "admin", "control", "superadmin"),
        "GE": ("auditor", "admin"),
    },
    ("admin", "HQ"): {"HQ": ("auditor", "control"), "GE": ("auditor", "admin")},
    ("control", "HQ"): {"HQ": ("control",), "GE": ()},
    ("admin", "GE"): {"HQ": (), "GE": ("auditor", "admin"), "AM": ()},
}


@pytest.mark.parametrize(
    ("кто", "пространство"),
    [(кто, пр) for кто, по in ВЫДАЁТ.items() for пр in по],
)
def test_какие_роли_выдаются(кто: tuple[str, str], пространство: str) -> None:
    охват = scope_of(*кто)
    assert охват is not None
    assert grantable_roles(охват, пространство) == ВЫДАЁТ[кто][пространство]
    for роль in ("auditor", "admin", "control", "superadmin", "owner"):
        assert may_grant(охват, tenant=пространство, role=роль) is (
            роль in ВЫДАЁТ[кто][пространство]
        )


def test_главного_админа_выдаёт_только_главный_админ() -> None:
    for кто in (("admin", "HQ"), ("control", "HQ"), ("admin", "GE")):
        охват = scope_of(*кто)
        assert охват is not None
        assert not may_grant(охват, tenant="HQ", role="superadmin"), кто
        assert not may_touch(охват, tenant="HQ", role="superadmin"), кто


def test_пространства_ведут_главный_админ_и_админ_уК() -> None:
    итог = {
        кто: manages_spaces(охват)
        for кто in (("superadmin", "HQ"), ("admin", "HQ"), ("control", "HQ"), ("admin", "GE"))
        if (охват := scope_of(*кто)) is not None
    }
    assert итог == {
        ("superadmin", "HQ"): True,
        ("admin", "HQ"): True,
        ("control", "HQ"): False,
        ("admin", "GE"): False,
    }


def test_пространства_в_форме_заведения() -> None:
    все = ("AM", "GE", "HQ")
    охваты = {кто: scope_of(*кто) for кто in (("superadmin", "HQ"), ("control", "HQ"))}
    охваты[("admin", "HQ")] = scope_of("admin", "HQ")
    охваты[("admin", "GE")] = scope_of("admin", "GE")
    assert {кто: spaces_for_add(о, все) for кто, о in охваты.items() if о} == {
        ("superadmin", "HQ"): все,
        ("admin", "HQ"): все,
        ("control", "HQ"): ("HQ",),
        ("admin", "GE"): ("GE",),
    }
