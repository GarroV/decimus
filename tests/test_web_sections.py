"""Реестр разделов веб-админки: состав, порядок и признак «построен» (D138).

`check_registry` — единственное место, которое сверяет реестр с экранами,
которые приложение зарегистрировало на самом деле; расхождение — отказ, а не
тихая ложь в навигации (см. `src/web/sections.py`).
"""

from __future__ import annotations

import pytest
from web_harness import войти, подменить_двери, собрать

from src.web import action_plans
from src.web.errors import SectionRegistryError
from src.web.sections import (
    SECTIONS,
    built_keys,
    check_registry,
    refused_for,
    section,
    visible_sections,
)


def test_sections_are_the_nine_from_the_prototype_in_order() -> None:
    """Девять разделов прототипа плюс «Люди» (T338): заведение учёток
    переехало из командной строки на экран, и в прототипе его не было.
    """
    assert [item.key for item in SECTIONS] == [
        "overview",
        "registry",
        "plans",
        "orders",
        "country",
        "calendar",
        "admin",
        "tenants",
        "actions",
        "users",
        "mini",
    ]


def test_built_keys_are_the_built_screens() -> None:
    assert built_keys() == frozenset(
        {"overview", "registry", "plans", "orders", "country", "admin", "users", "actions"}
    )


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
        ("overview", "registry", "plans", "orders", "country", "admin", "users", "actions")
    )


def test_check_registry_refuses_a_built_section_left_without_a_screen() -> None:
    with pytest.raises(SectionRegistryError, match="registry"):
        check_registry(("admin", "users"))


def test_check_registry_refuses_a_screen_for_an_unbuilt_section() -> None:
    with pytest.raises(SectionRegistryError, match="calendar"):
        check_registry(
            (
                "overview",
                "registry",
                "plans",
                "orders",
                "actions",
                "country",
                "admin",
                "users",
                "calendar",
            )
        )


def test_check_registry_refuses_a_screen_outside_the_registry() -> None:
    with pytest.raises(SectionRegistryError, match="выдумка"):
        check_registry(("overview", "registry", "country", "admin", "users", "выдумка"))


# --- разделы «только УК» (D264, волна 1 #340) -------------------------------


class _Кто:
    def __init__(self, tenant: str, role: str = "auditor") -> None:
        self.tenant, self.role = tenant, role


def test_раздел_уК_скрыт_у_партнёра() -> None:
    assert "tenants" not in {s.key for s in visible_sections(_Кто("GE"))}
    assert "tenants" in {s.key for s in visible_sections(_Кто("HQ"))}
    assert "tenants" in {s.key for s in visible_sections(_Кто("default"))}


def test_пользователи_видны_каждому() -> None:
    assert "users" in {s.key for s in visible_sections(_Кто("GE"))}


def test_адрес_раздела_уК_отказывает_партнёру_и_вложенный_тоже() -> None:
    путь = section("tenants").path
    assert refused_for(путь, "GE") and refused_for(путь + "/GE", "GE")
    assert not refused_for(путь, "HQ")
    assert not refused_for(section("registry").path, "GE")


def test_каждый_раздел_только_уК_закрыт_партнёру(monkeypatch: pytest.MonkeyPatch) -> None:
    """Партнёру — тот же 404, что у несуществующего адреса, на каждом разделе «только УК»."""
    подменить_двери(monkeypatch, tenant="GE", role="admin")
    закрытые = [s for s in SECTIONS if s.hq_only]
    assert закрытые, "ни один раздел не помечен — тест ничего не проверяет"
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        нет = client.get("/nothing-here-at-all")
        for s in закрытые:
            ответ = client.get(s.path)
            assert ответ.status_code == 404, s.key
            # Тот же ответ с точностью до адреса: форма языка шлёт на текущий путь.
            свой_адрес = s.path.encode()
            assert ответ.data.replace(свой_адрес, b"") == нет.data.replace(
                b"/nothing-here-at-all", b""
            ), s.key


def test_раздел_только_уК_открыт_уК(monkeypatch: pytest.MonkeyPatch) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        monkeypatch.setattr(action_plans.plans, "list_requests", lambda **_: action_plans.EMPTY)
        for s in (s for s in SECTIONS if s.hq_only):
            assert client.get(s.path).status_code == 200, s.key
