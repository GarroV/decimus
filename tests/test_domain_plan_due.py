"""Срок ответа планом — один, из методики (D617)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import методика_со_сроком

from src.domain.errors import ConfigError
from src.domain.plan_due import plan_due_days


def test_срок_берётся_из_методики(
    domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIT_DATA_DIR", str(методика_со_сроком(tmp_path, 12)))
    assert plan_due_days() == 12


def test_синтетическая_методика_держит_десять_дней(domain_env: Path) -> None:
    assert plan_due_days() == 10


@pytest.mark.parametrize("мусор", [None, "семь", 0, 366, True, 7.5])
def test_мусор_в_сроке_это_отказ(
    мусор: object, domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUDIT_DATA_DIR", str(методика_со_сроком(tmp_path, мусор)))
    with pytest.raises(ConfigError, match="plan_due_days"):
        plan_due_days()
