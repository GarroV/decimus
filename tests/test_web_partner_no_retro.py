"""Партнёр задним числом не меняет ничего (D341), но вычитывает свежее (D367).

Снятие и перенос — только админу УК и главному админу. Приёмку и правку записи
админ партнёра делает ровно в одном случае: свежая (ещё на приёмке) проверка
из обхода его пространства, то есть проведённая его сотрудниками. Принятую,
проверку УК или стороннего проверяющего он не трогает — 403, двери записи не
зовутся. Заслон — на маршруте: адрес известен, и POST набирается руками.
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


def _двери(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant: str,
    role: str,
    ждёт: bool,
    владелец: str | None = None,
    origin: str = "field",
) -> list[str]:
    """Вошедший `role` в `tenant`; проверка — пространства `владелец` (по умолчанию
    своего); двери записи пишут зовы."""
    зовы: list[str] = []
    деталь = карточка(шапка(on_review=ждёт, tenant_code=владелец or tenant, origin=origin))
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
@pytest.mark.parametrize("адрес", [АДРЕСА[0], АДРЕСА[3]])
def test_админ_партнёра_не_снимает_и_не_переносит(
    monkeypatch: pytest.MonkeyPatch, адрес: str, ждёт: bool
) -> None:
    зовы = _двери(monkeypatch, tenant=ПАРТНЁР, role="admin", ждёт=ждёт)
    ответ = _отправить(адрес)
    assert ответ.status_code == 403, ответ.data[:300]
    assert зовы == [], f"дверь записи вызвана админом партнёра: {зовы}"


@pytest.mark.parametrize(
    ("адрес", "дверь"), [(АДРЕСА[1], "accept_card"), (АДРЕСА[2], "revise_card")]
)
def test_админ_партнёра_вычитывает_свежую_проверку_своих(
    monkeypatch: pytest.MonkeyPatch, адрес: str, дверь: str
) -> None:
    """D367: свежая проверка сотрудников партнёра — принимает и правит он сам."""
    зовы = _двери(monkeypatch, tenant=ПАРТНЁР, role="admin", ждёт=True)
    ответ = _отправить(адрес)
    assert ответ.status_code == 200, ответ.data[:300]
    assert зовы == [дверь]


@pytest.mark.parametrize("адрес", [АДРЕСА[1], АДРЕСА[2]])
@pytest.mark.parametrize(
    "случай",
    [
        {"ждёт": False},  # уже принята — правки после приёмки закрыты (D341)
        {"ждёт": True, "владелец": "HQ"},  # проверка УК или стороннего проверяющего
        {"ждёт": True, "origin": "import"},  # заведена не обходом
        {"ждёт": True, "role": "auditor"},  # не админ
    ],
)
def test_партнёр_не_вычитывает_чужое_и_принятое(
    monkeypatch: pytest.MonkeyPatch, адрес: str, случай: dict[str, object]
) -> None:
    параметры: dict[str, object] = {"role": "admin", **случай}
    зовы = _двери(monkeypatch, tenant=ПАРТНЁР, **параметры)  # type: ignore[arg-type]
    ответ = _отправить(адрес)
    assert ответ.status_code in (403, 404), ответ.data[:300]
    assert зовы == [], f"дверь записи вызвана: {зовы}"


def _страница(monkeypatch: pytest.MonkeyPatch, **параметры: object) -> str:
    _двери(monkeypatch, tenant=ПАРТНЁР, role="admin", **параметры)  # type: ignore[arg-type]
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        return client.get(f"/inspections/{ID}").get_data(as_text=True)


def test_у_принятой_у_партнёра_кнопок_правки_нет(monkeypatch: pytest.MonkeyPatch) -> None:
    страница = _страница(monkeypatch, ждёт=False)
    for действие in ("/accept?lang=", "/revise?lang=", "/move?lang=", "/retract?lang="):
        assert действие not in страница, действие


def test_у_свежей_своей_партнёр_видит_приёмку_но_не_снятие(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    страница = _страница(monkeypatch, ждёт=True)
    assert "/accept?lang=" in страница
    for действие in ("/move?lang=", "/retract?lang="):
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
