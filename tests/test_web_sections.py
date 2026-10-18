"""Реестр разделов веб-админки: состав, порядок и признак «построен» (D138).

`check_registry` — единственное место, которое сверяет реестр с экранами,
которые приложение зарегистрировало на самом деле; расхождение — отказ, а не
тихая ложь в навигации (см. `src/web/sections.py`).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from web_harness import войти, подменить_двери, собрать

from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.web import sections
from src.web.errors import SectionRegistryError
from src.web.sections import (
    SECTIONS,
    built_keys,
    check_registry,
    refused_for,
    section,
    visible_sections,
)


def test_sections_go_in_menu_groups_in_order() -> None:
    """Разделы по группам меню (D499): проверки, статистика, администрирование."""
    assert [(item.group, item.key) for item in SECTIONS] == [
        ("work", "overview"),
        ("work", "registry"),
        ("work", "calendar"),
        ("work", "actions"),
        ("stats", "country"),
        ("stats", "ratings"),
        ("admin", "admin"),
        ("admin", "users"),
        ("admin", "settings"),
    ]


def test_built_keys_are_the_built_screens() -> None:
    assert built_keys() == frozenset(
        {
            "overview",
            "registry",
            "country",
            "ratings",
            "calendar",
            "admin",
            "users",
            "settings",
            "actions",
        }
    )


def test_settings_is_not_in_the_menu_of_any_role() -> None:
    """«Настройки» — профиль, в него ведёт аватар, а не пункт левой панели (D447)."""
    for tenant, role in (("HQ", "superadmin"), ("HQ", "control"), ("HQ", "guest"), ("GE", "admin")):
        меню = {s.key for s in visible_sections(_Кто(tenant, role))}
        assert "settings" not in меню, (tenant, role)


def test_keys_and_paths_are_unique_and_paths_are_absolute() -> None:
    keys = [item.key for item in SECTIONS]
    paths = [item.path for item in SECTIONS]
    assert len(keys) == len(set(keys)), "ключи разделов повторяются"
    assert len(paths) == len(set(paths)), "адреса разделов повторяются"
    assert all(path.startswith("/") for path in paths), "адрес раздела не абсолютный"


def test_section_returns_the_built_registry_section() -> None:
    assert section("registry").built is True


def test_section_refuses_an_unknown_key() -> None:
    with pytest.raises(SectionRegistryError):
        section("нет-такого")


def test_check_registry_accepts_exactly_the_built_sections() -> None:
    check_registry(
        (
            "overview",
            "registry",
            "country",
            "ratings",
            "calendar",
            "admin",
            "users",
            "settings",
            "actions",
        )
    )


def test_check_registry_refuses_a_built_section_left_without_a_screen() -> None:
    with pytest.raises(SectionRegistryError, match="registry"):
        check_registry(("admin", "users"))


def test_check_registry_refuses_a_built_calendar_left_without_a_screen() -> None:
    """«Календарь» построен (D466): экрана нет — приложение не собирается."""
    with pytest.raises(SectionRegistryError, match="calendar"):
        check_registry(
            (
                "overview",
                "registry",
                "actions",
                "country",
                "ratings",
                "admin",
                "users",
                "settings",
            )
        )


def test_check_registry_refuses_a_screen_for_an_unbuilt_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Непостроенных разделов в реестре сейчас нет, поэтому один снимается на время теста."""
    monkeypatch.setattr(
        sections,
        "SECTIONS",
        tuple(replace(item, built=False) if item.key == "calendar" else item for item in SECTIONS),
    )
    with pytest.raises(SectionRegistryError, match="calendar"):
        check_registry(sections.built_keys() | {"calendar"})


def test_check_registry_refuses_a_screen_outside_the_registry() -> None:
    with pytest.raises(SectionRegistryError, match="выдумка"):
        check_registry(("overview", "registry", "country", "admin", "users", "settings", "выдумка"))


# --- «Действия» — один раздел у УК и партнёра (D526) -----------------------


class _Кто:
    def __init__(self, tenant: str, role: str | None = None) -> None:
        # Рабочая роль стороны (D440): в УК аудитора нет — бизнес-девелопер.
        if role is None:
            role = "developer" if canonical_tenant(tenant) == HQ_TENANT else "auditor"
        self.tenant, self.role = tenant, role


@pytest.mark.parametrize("пространство", ["HQ", "default", "GE"])
def test_действия_видны_и_уК_и_партнёру_а_старых_разделов_партнёра_нет(пространство: str) -> None:
    """D526: один раздел «Действия» у обеих сторон; `plans` и `orders` из меню ушли."""
    ключи = {s.key for s in visible_sections(_Кто(пространство))}
    assert "actions" in ключи
    assert not ключи & {"plans", "orders"}


def test_старых_разделов_партнёра_нет_в_реестре() -> None:
    assert not {"plans", "orders"} & {s.key for s in SECTIONS}


def test_раздела_проект_нет_пространства_на_экране_пользователей() -> None:
    """#585: пространства партнёров ведутся на «Пользователях», заглушки «Проект» нет."""
    assert "tenants" not in {s.key for s in SECTIONS}


def test_пользователи_видны_каждому() -> None:
    assert "users" in {s.key for s in visible_sections(_Кто("GE"))}


# --- флаг «только УК» — механизм, которым сейчас не пользуется ни один раздел


@pytest.fixture
def раздел_только_уК(monkeypatch: pytest.MonkeyPatch) -> str:
    """Раздел «Календарь» на время теста помечен «только УК» — механизм жив и проверяется."""
    monkeypatch.setattr(
        sections,
        "SECTIONS",
        tuple(replace(s, hq_only=True) if s.key == "calendar" else s for s in SECTIONS),
    )
    return "calendar"


def test_адрес_раздела_только_уК_отказывает_партнёру_и_вложенному(раздел_только_уК: str) -> None:
    путь = section(раздел_только_уК).path
    assert refused_for(путь, "GE") and refused_for(путь + "/GE", "GE")
    assert not refused_for(путь, "HQ")
    assert not refused_for(section("registry").path, "GE")


def test_раздел_только_уК_отвечает_партнёру_404(
    monkeypatch: pytest.MonkeyPatch, раздел_только_уК: str
) -> None:
    """Партнёру — тот же 404, что у несуществующего адреса (D264)."""
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    путь = section(раздел_только_уК).path
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        assert client.get("/nothing-here-at-all").status_code == 404
        assert client.get(путь).status_code == 404
