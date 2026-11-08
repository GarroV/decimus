"""Переключатель пространств (D726): правила «кому» и «куда» — ядро прав доступа."""

from __future__ import annotations

import pytest

from src.domain import peek


def test_главный_админ_ук_после_второй_ступени_может() -> None:
    assert peek.may_peek(role="superadmin", tenant="HQ", second_step_ok=True)
    # Старый код тенанта УК — то же пространство (D234).
    assert peek.may_peek(role="superadmin", tenant="default", second_step_ok=True)


@pytest.mark.parametrize("роль", ["admin", "developer", "control", "guest", "osb", "auditor"])
def test_прочие_роли_ук_не_могут(роль: str) -> None:
    assert not peek.may_peek(role=роль, tenant="HQ", second_step_ok=True)


def test_партнёр_не_может_даже_с_ролью_админа() -> None:
    assert not peek.may_peek(role="admin", tenant="TEST", second_step_ok=True)
    assert not peek.may_peek(role="superadmin", tenant="TEST", second_step_ok=True)


def test_без_второй_ступени_нельзя() -> None:
    assert not peek.may_peek(role="superadmin", tenant="HQ", second_step_ok=False)


def test_цель_только_из_перечня_или_домой() -> None:
    assert peek.target_of("TEST") == "TEST"
    assert peek.target_of("HQ") is None


@pytest.mark.parametrize(
    "код", ["", "  ", "test", "OTHER", "default", "TEST ' or 1=1 --", "SI", None]
)
def test_произвольная_цель_отказ(код: str | None) -> None:
    with pytest.raises(ValueError):
        peek.target_of(код)


def test_партнёрская_роль_подмены_админ() -> None:
    assert peek.PEEK_ROLE == "admin"
