"""Методику правят только админы (D344): заслон на запись в разделе «Методика».

Маршруты `/admin/*` своей проверки роли не имеют — их закрывает один заслон
`before_request`, поэтому новый правящий маршрут закрыт с момента появления.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, войти, подменить_двери, собрать

ЗАГОЛОВКИ = {"Origin": СВОЙ}

ПРАВКИ = [
    ("/admin/items", {"code": "X1", "name_ru": "x", "name_en": "x"}),
    ("/admin/zones", {"code": "Z1", "name_ru": "x", "name_en": "x"}),
    ("/admin/scoring", {}),
    ("/admin/checklists", {"code": "c1"}),
]


def _клиент(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant=tenant).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def аудитор_ук(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _клиент(monkeypatch, tenant="HQ", role="auditor")


@pytest.fixture
def сотрудник_партнёра(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _клиент(monkeypatch, tenant="GE", role="auditor")


@pytest.fixture
def админ_ук(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _клиент(monkeypatch, tenant="HQ", role="admin")


@pytest.mark.parametrize(("путь", "форма"), ПРАВКИ)
def test_аудитор_ук_не_правит_методику(
    аудитор_ук: FlaskClient, путь: str, форма: dict[str, str]
) -> None:
    assert аудитор_ук.post(путь, data=форма, headers=ЗАГОЛОВКИ).status_code == 403


@pytest.mark.parametrize(("путь", "форма"), ПРАВКИ)
def test_сотрудник_партнёра_не_правит_методику(
    сотрудник_партнёра: FlaskClient, путь: str, форма: dict[str, str]
) -> None:
    assert сотрудник_партнёра.post(путь, data=форма, headers=ЗАГОЛОВКИ).status_code == 403


def test_аудитор_методику_читает(аудитор_ук: FlaskClient) -> None:
    assert аудитор_ук.get("/admin").status_code == 200


@pytest.mark.parametrize(("путь", "форма"), ПРАВКИ)
def test_админа_заслон_пропускает(админ_ук: FlaskClient, путь: str, форма: dict[str, str]) -> None:
    """Дальше решает сам маршрут (форма может быть неполной), но не заслон: не 403."""
    assert админ_ук.post(путь, data=форма, headers=ЗАГОЛОВКИ).status_code != 403


def test_экран_людей_не_кэшируется(админ_ук: FlaskClient) -> None:
    """Новый пароль показывается один раз — копия страницы не должна остаться в кэше."""
    assert админ_ук.get("/users").headers.get("Cache-Control") == "no-store"
