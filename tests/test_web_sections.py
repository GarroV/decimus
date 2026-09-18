"""Реестр разделов веб-админки: состав, порядок и признак «построен» (D138).

`check_registry` — единственное место, которое сверяет реестр с экранами,
которые приложение зарегистрировало на самом деле; расхождение — отказ, а не
тихая ложь в навигации (см. `src/web/sections.py`).
"""

from __future__ import annotations

import pytest

from src.web.errors import SectionRegistryError
from src.web.sections import SECTIONS, built_keys, check_registry, section


def test_sections_are_the_nine_from_the_prototype_in_order() -> None:
    assert [item.key for item in SECTIONS] == [
        "overview",
        "registry",
        "plans",
        "orders",
        "country",
        "calendar",
        "admin",
        "tenants",
        "mini",
    ]


def test_built_keys_is_only_registry() -> None:
    assert built_keys() == frozenset({"registry"})


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


def test_check_registry_accepts_exactly_the_built_section() -> None:
    check_registry(("registry",))


def test_check_registry_refuses_a_built_section_left_without_a_screen() -> None:
    with pytest.raises(SectionRegistryError, match="registry"):
        check_registry(())


def test_check_registry_refuses_a_screen_for_an_unbuilt_section() -> None:
    with pytest.raises(SectionRegistryError, match="plans"):
        check_registry(("registry", "plans"))


def test_check_registry_refuses_a_screen_outside_the_registry() -> None:
    with pytest.raises(SectionRegistryError, match="выдумка"):
        check_registry(("выдумка",))
