"""Кто загружает рейтинги и правит их справочники (D319, спека «Роль «контроль»»)."""

from __future__ import annotations

import pytest

from src.domain.tenants import may_manage_ratings


@pytest.mark.parametrize(
    ("role", "tenant", "можно"),
    [
        ("control", "HQ", True),
        ("admin", "HQ", True),
        # Код пространства регистрозависим, как в `may_add_units`: тенант пишется кодом `HQ`.
        ("admin", "hq", False),
        ("auditor", "HQ", False),
        ("admin", "GE", False),
        ("control", "GE", False),
        (None, "HQ", False),
    ],
)
def test_рейтинги_правят_контроль_и_админ_уК(role: str | None, tenant: str, можно: bool) -> None:
    assert may_manage_ratings(role, tenant) is можно
