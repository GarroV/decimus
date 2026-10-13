"""GHSA-pchf-85ph-vg9x: успешный вход не сбрасывает счётчик адреса.

Раньше `note_success` забывал и логин, и адрес: перебор с одного адреса
обходился чередованием с входом под своей учёткой — каждый успех обнулял счёт,
и порог по адресу не достигался. Набор без базы: хранилище счётчика подменено
в памяти, правило (`verdict_of`, пороги) — продуктовое.
"""

from __future__ import annotations

import pytest
from web_harness import Счётчики, подменить_счётчики

from src.db.web_throttle import (
    FAILURES_BEFORE_LOCK,
    SCOPE_ADDRESS,
    SCOPE_LOGIN,
    admit_attempt,
    canonical_address,
    key_fingerprint,
    note_success,
)

ТЕНАНТ = "HQ"
АДРЕС = "203.0.113.7"
СВОЙ_ЛОГИН = "own-account"


@pytest.fixture
def счётчики(monkeypatch: pytest.MonkeyPatch) -> Счётчики:
    return подменить_счётчики(monkeypatch)


def test_успех_сбрасывает_счётчик_своего_логина(счётчики: Счётчики) -> None:
    admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=СВОЙ_ЛОГИН)

    note_success(tenant=ТЕНАНТ, login=СВОЙ_ЛОГИН)

    assert (
        счётчики.load(tenant=ТЕНАНТ, scope=SCOPE_LOGIN, fingerprint=key_fingerprint(СВОЙ_ЛОГИН))
        is None
    )


def test_успех_не_сбрасывает_счётчик_адреса(счётчики: Счётчики) -> None:
    """Перебор чужих логинов с адреса, чередуемый со своим входом, доходит до порога."""
    адрес_ключ = key_fingerprint(canonical_address(АДРЕС))
    порог = FAILURES_BEFORE_LOCK[SCOPE_ADDRESS]

    for номер in range(порог - 1):
        admit_attempt(tenant=ТЕНАНТ, address=АДРЕС, login=f"victim-{номер}")
        note_success(tenant=ТЕНАНТ, login=СВОЙ_ЛОГИН)

    строка = счётчики.load(tenant=ТЕНАНТ, scope=SCOPE_ADDRESS, fingerprint=адрес_ключ)
    assert строка is not None
    assert строка.failures == порог - 1, "счётчик адреса обнулён успешным входом"
