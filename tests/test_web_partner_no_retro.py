"""Партнёр задним числом не меняет ничего (D341).

Снятие, приёмка, правка записи и перенос проверки — только админу УК и
главному админу. Админ пространства партнёра получает 403 даже по проверке
своего пространства, и ни одна дверь записи не зовётся; кнопок на карточке у
него нет. Заслон — на маршруте: адрес известен, и POST набирается руками.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_web_app import карточка, шапка
from web_harness import СВОЙ, войти, охват_без_базы, подменить_двери, собрать
from werkzeug.test import TestResponse as FlaskResponse

from src.web import auth, revision
from src.web import inspections as data

ПАРТНЁР = "GE"
ID = "11111111-1111-1111-1111-111111111111"
ДВЕРИ_ЗАПИСИ = ("retract_card", "accept_card", "move_card")
АДРЕСА = (
    f"/inspections/{ID}/retract",
    f"/inspections/{ID}/accept",
    f"/inspections/{ID}/findings/f1/revise",
    f"/inspections/{ID}/move",
)
ФОРМА = {"reason": "x", "date": "2026-10-01", "unit": "u", "code": "CLN05", "level": "D2"}


def _двери(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str, ждёт: bool) -> list[str]:
    """Вошедший `role` в `tenant`; проверка — своего пространства; двери записи пишут зовы."""
    зовы: list[str] = []
    деталь = карточка(шапка(on_review=ждёт, tenant_code=tenant))
    monkeypatch.setattr(data, "retraction_available", lambda: True)
    monkeypatch.setattr(data, "load_card", lambda *_a, **_k: деталь)
    monkeypatch.setattr(data, "load_moves", lambda *_a, **_k: ())
    monkeypatch.setattr(data, "load_units", lambda **_: ())
    for имя in ДВЕРИ_ЗАПИСИ:

        def дверь(*_a: object, _имя: str = имя, **_k: object) -> SimpleNamespace:
            зовы.append(_имя)
            return SimpleNamespace(photos_purged=0)

        monkeypatch.setattr(data, имя, дверь)
    monkeypatch.setattr(revision, "revise_card", lambda *_a, **_k: зовы.append("revise_card"))
    monkeypatch.setattr(auth, "reach_of", охват_без_базы)
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    return зовы


def _отправить(адрес: str) -> FlaskResponse:
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        return client.post(адрес, data=ФОРМА, headers={"Origin": СВОЙ})


@pytest.mark.parametrize("ждёт", [True, False])
@pytest.mark.parametrize("адрес", АДРЕСА)
def test_админ_партнёра_не_меняет_свою_проверку(
    monkeypatch: pytest.MonkeyPatch, адрес: str, ждёт: bool
) -> None:
    # Arrange
    зовы = _двери(monkeypatch, tenant=ПАРТНЁР, role="admin", ждёт=ждёт)

    # Act
    ответ = _отправить(адрес)

    # Assert
    assert ответ.status_code == 403, ответ.data[:300]
    assert зовы == [], f"дверь записи вызвана админом партнёра: {зовы}"


@pytest.mark.parametrize("ждёт", [True, False])
def test_админу_партнёра_кнопок_правки_на_карточке_нет(
    monkeypatch: pytest.MonkeyPatch, ждёт: bool
) -> None:
    # Arrange
    _двери(monkeypatch, tenant=ПАРТНЁР, role="admin", ждёт=ждёт)

    # Act
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        страница = client.get(f"/inspections/{ID}").get_data(as_text=True)

    # Assert
    for действие in ("/accept?lang=", "/revise?lang=", "/move?lang=", "/retract?lang="):
        assert действие not in страница, действие


@pytest.mark.parametrize("role", ["admin", "superadmin"])
@pytest.mark.parametrize(
    ("адрес", "дверь", "ждёт"),
    [
        (АДРЕСА[0], "retract_card", False),
        (АДРЕСА[1], "accept_card", True),
        (АДРЕСА[2], "revise_card", True),
    ],
)
def test_админ_и_главный_админ_уК_меняют_свою_проверку(
    monkeypatch: pytest.MonkeyPatch, role: str, адрес: str, дверь: str, ждёт: bool
) -> None:
    # Arrange
    зовы = _двери(monkeypatch, tenant="HQ", role=role, ждёт=ждёт)

    # Act
    ответ = _отправить(адрес)

    # Assert
    assert ответ.status_code == 200, ответ.data[:300]
    assert зовы == [дверь]
