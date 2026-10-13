"""Окна и право снимать способы входа (D463): чистые правила без базы."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.domain.second_factor import (
    enrollment_window,
    is_fresh_login,
    may_remove_factor,
)

СЕЙЧАС = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


def test_у_админа_без_способа_окно_пять_минут() -> None:
    assert enrollment_window("admin", has_factor=False) == timedelta(minutes=5)
    assert enrollment_window("superadmin", has_factor=False) == timedelta(minutes=5)


def test_у_остальных_и_у_админа_со_способом_десять() -> None:
    assert enrollment_window("developer", has_factor=False) == timedelta(minutes=10)
    assert enrollment_window("admin", has_factor=True) == timedelta(minutes=10)


def test_свежесть_считается_по_окну_роли() -> None:
    шесть = СЕЙЧАС - timedelta(minutes=6)

    assert not is_fresh_login(шесть, role="admin", has_factor=False, now=СЕЙЧАС)
    assert is_fresh_login(шесть, role="developer", has_factor=False, now=СЕЙЧАС)
    assert not is_fresh_login(None, role="developer", has_factor=False, now=СЕЙЧАС)


def test_снимать_способ_можно_только_после_второй_ступени_и_свежим_входом() -> None:
    свежий = СЕЙЧАС - timedelta(minutes=1)
    старый = СЕЙЧАС - timedelta(minutes=11)
    общее = {"role": "admin", "has_factor": True, "now": СЕЙЧАС}

    assert may_remove_factor(passed_second_step=True, signed_in_at=свежий, **общее)
    assert not may_remove_factor(passed_second_step=False, signed_in_at=свежий, **общее)
    assert not may_remove_factor(passed_second_step=True, signed_in_at=старый, **общее)
