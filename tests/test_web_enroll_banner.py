"""Плашка «подключите вход в два шага» (D483): админу без второго способа — на каждой странице.

Без базы: двери опознания подменены оснасткой, а вошедшего с нужными ролью и признаком
способа отдаёт `resolve_session` этого набора.
"""

from __future__ import annotations

import pytest
from web_harness import ТОКЕН, Учётка, войти, подменить_двери, собрать

from src.domain.tenants import HQ_TENANT
from src.web import auth

ТЕНАНТ = HQ_TENANT
МАРКЕР = "data-enroll-banner"


def _страница(
    monkeypatch: pytest.MonkeyPatch, *, роль: str, есть_способ: bool, путь: str = "/settings"
) -> str:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role=роль)
    monkeypatch.setattr(
        auth,
        "resolve_session",
        lambda token: (
            Учётка(tenant=ТЕНАНТ, role=роль, has_second_factor=есть_способ)
            if token == ТОКЕН
            else None
        ),
    )
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        ответ = client.get(путь, follow_redirects=True)
        assert ответ.status_code == 200, ответ.status_code
        return ответ.get_data(as_text=True)


def test_админу_без_способа_плашка_ведёт_на_вход_и_защиту(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    страница = _страница(monkeypatch, роль="admin", есть_способ=False)

    assert МАРКЕР in страница
    assert "Подключите вход в два шага" in страница
    assert 'href="/settings/security?lang=ru"' in страница


def test_главному_админу_без_способа_плашка_тоже_есть(monkeypatch: pytest.MonkeyPatch) -> None:
    assert МАРКЕР in _страница(monkeypatch, роль="superadmin", есть_способ=False)


def test_админу_со_способом_плашки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    assert МАРКЕР not in _страница(monkeypatch, роль="admin", есть_способ=True)


def test_разработчику_без_способа_плашки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    assert МАРКЕР not in _страница(monkeypatch, роль="developer", есть_способ=False)
