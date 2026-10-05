"""Новая пиццерия из веб-админки: кого экран пускает и что передаёт базе (#437).

Права — ядро: ошибка здесь не кричит. Партнёр, заведший точку в справочник
УК, или точка, молча обновившая чужую строку, выглядят обычными данными.
Поэтому проверяется прежде всего, КОГО маршрут пускает к двери базы и с чем.
Слой базы подменён на границе: его поведение — `test_db_unit_create.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from test_web_country import данные, открыть
from web_harness import СВОЙ, войти, подменить_двери, собрать

from src.db.errors import PushError, UnitExistsError
from src.db.reach import Reach
from src.web import app as app_mod
from src.web import unit_add

ЗАГОЛОВКИ = {"Origin": СВОЙ}
АДРЕС = "/country/RS/units/new"


@pytest.fixture
def заведено(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    позвали: list[dict[str, Any]] = []

    def _create(name: str, **поля: Any) -> str:
        позвали.append({"name": name, **поля})
        if name == "Belgrade-1":
            raise UnitExistsError("есть", unit_id="u-old", name="Belgrade-1")
        if name == "Novi Sad-9":
            raise PushError("база не ответила")
        return "u-new"

    monkeypatch.setattr(unit_add.directory, "create_unit", _create)
    monkeypatch.setattr(app_mod.country_data, "countries", lambda **_: (("RS", 1),))
    return позвали


def стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def уК(monkeypatch: pytest.MonkeyPatch, заведено: Any) -> Iterator[FlaskClient]:
    yield from стенд(monkeypatch, tenant="HQ", role="auditor")


@pytest.fixture
def партнёр(monkeypatch: pytest.MonkeyPatch, заведено: Any) -> Iterator[FlaskClient]:
    # Охват партнёра — страна его кода (`web_harness.охват_без_базы`): RS.
    yield from стенд(monkeypatch, tenant="RS", role="admin")


def отправить(client: FlaskClient, **форма: str) -> Any:
    return client.post(АДРЕС, data=форма, headers=ЗАГОЛОВКИ)


# --- права -----------------------------------------------------------------


def test_уК_открывает_форму(уК: FlaskClient) -> None:
    ответ = уК.get(АДРЕС)
    assert ответ.status_code == 200
    assert 'name="name"' in ответ.get_data(as_text=True)


def test_партнёр_не_видит_ни_формы_ни_записи(
    партнёр: FlaskClient, заведено: list[dict[str, Any]]
) -> None:
    # Своя страна партнёра — и всё равно нет: справочник пополняет только УК (D234).
    assert партнёр.get(АДРЕС).status_code == 404
    assert отправить(партнёр, name="Belgrade-6").status_code == 404
    assert заведено == []


@pytest.mark.parametrize("код", ["ZZ", "R5", "RSS"])
def test_страна_вне_словаря_как_несуществующий_адрес(
    уК: FlaskClient, заведено: list[dict[str, Any]], код: str
) -> None:
    assert уК.get(f"/country/{код}/units/new").status_code == 404
    ответ = уК.post(f"/country/{код}/units/new", data={"name": "X-1"}, headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 404
    assert заведено == []


def test_страна_вне_охвата_закрыта() -> None:
    узкий = Reach("HQ", None, ("GE",))
    assert unit_add.may_add_in("HQ", узкий, "GE")
    assert not unit_add.may_add_in("HQ", узкий, "RS")
    assert unit_add.may_add_in("HQ", Reach("HQ", None, None), "RS")
    assert not unit_add.may_add_in("RS", Reach("RS", None, None), "RS")


def test_чужой_источник_запроса_отказ(уК: FlaskClient, заведено: list[dict[str, Any]]) -> None:
    ответ = уК.post(АДРЕС, data={"name": "Belgrade-6"}, headers={"Origin": "https://evil.example"})
    assert ответ.status_code == 403
    assert заведено == []


def test_вход_на_экране_страны_только_у_уК(monkeypatch: pytest.MonkeyPatch, заведено: Any) -> None:
    for tenant, виден in (("HQ", True), ("GE", False)):
        for client in стенд(monkeypatch, tenant=tenant, role="admin"):
            страница = открыть(client, monkeypatch, данные(), "/country/GE")
            assert ("/country/GE/units/new" in страница) is виден, tenant


# --- что уходит в базу -------------------------------------------------------


def test_заводит_каноническое_имя_со_страной_и_синонимом(
    уК: FlaskClient, заведено: list[dict[str, Any]]
) -> None:
    ответ = отправить(уК, name="Белград 6")
    assert ответ.status_code == 302
    assert "/units/u-new" in ответ.headers["Location"] and "added=1" in ответ.headers["Location"]
    assert заведено == [
        {
            "name": "Belgrade-6",
            "country": "RS",
            "city": "beograd",
            "aliases": ("Белград 6",),
            "tenant": "HQ",
        }
    ]


def test_дубль_отказ_со_ссылкой_на_существующую(
    уК: FlaskClient, заведено: list[dict[str, Any]]
) -> None:
    ответ = отправить(уК, name="Белград-1")
    страница = ответ.get_data(as_text=True)
    assert ответ.status_code == 409
    assert "Belgrade-1" in страница and "/units/u-old" in страница


def test_город_другой_страны_не_доходит_до_базы(
    уК: FlaskClient, заведено: list[dict[str, Any]]
) -> None:
    ответ = отправить(уК, name="Ереван-4")
    assert ответ.status_code == 400
    assert "Yerevan-4" in ответ.get_data(as_text=True)
    assert заведено == []


def test_без_номера_отказ_словами(уК: FlaskClient, заведено: list[dict[str, Any]]) -> None:
    ответ = отправить(уК, name="Земун")
    assert ответ.status_code == 400
    assert "Земун" in ответ.get_data(as_text=True)
    assert заведено == []


def test_незнакомый_город_сначала_переспрашивает(
    уК: FlaskClient, заведено: list[dict[str, Any]]
) -> None:
    первый = отправить(уК, name="Zemun 2")
    assert первый.status_code == 200
    assert 'name="confirm" value="Zemun-2"' in первый.get_data(as_text=True)
    assert заведено == []

    # Подтверждение другого имени не считается: имя поправили — переспросить.
    assert отправить(уК, name="Zemun 3", confirm="Zemun-2").status_code == 200
    assert заведено == []

    assert отправить(уК, name="Zemun 2", confirm="Zemun-2").status_code == 302
    assert [з["name"] for з in заведено] == ["Zemun-2"]
    assert заведено[0]["city"] is None and заведено[0]["country"] == "RS"


def test_отказ_базы_не_выдаётся_за_успех(уК: FlaskClient, заведено: list[dict[str, Any]]) -> None:
    ответ = отправить(уК, name="Нови Сад 9")
    assert ответ.status_code == 503
