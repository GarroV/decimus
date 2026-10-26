"""«Заморозить» и «Разморозить» на экране «Пользователи» (D462) — маршруты и карточка.

Ядро доступа: кто кого замораживает и кто размораживает. Слой базы подменён на
границе модуля; что делает заморозка со всеми дверями входа — `test_db_freeze.py`.

- замораживает тот, кто ведёт человека (`access_policy.may_touch`): главный админ —
  любого, кроме себя; админ УК — тех, кого уже ведёт, но не главного админа;
- размораживает только главный админ: заморозка — ответ на «учётку взломали», и
  снять её не должен такой же админ, чей вход мог быть взломанным;
- карточка называет, когда и кто заморозил, и не прячет заморозку за «отключено».
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.db import bot_links
from src.web import accounts

ЗАГОЛОВКИ = {"Origin": "http://localhost"}
АКТОР = "22222222-2222-2222-2222-222222222222"
ЗАМОРОЖЕН = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


def строка(
    login: str, tenant: str, role: str, *, заморожен_кем: str | None = None, заморожен: bool = False
) -> Any:
    return SimpleNamespace(
        login=login,
        role=role,
        tenant=tenant,
        email=f"{login}@mail.example",
        id=f"id-{login}",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=ЗАМОРОЖЕН if заморожен else None,
        disabled_by=заморожен_кем,
    )


ПЕРЕЧЕНЬ = (
    строка("boss2", "HQ", "superadmin"),
    строка("kostya", "HQ", "admin"),
    строка("vika", "HQ", "control"),
    строка("petr", "HQ", "developer"),
    строка("ghost", "HQ", "developer", заморожен=True, заморожен_кем="boss2"),
    строка("legacy", "HQ", "developer", заморожен=True),
    строка("nino", "GE", "admin"),
    строка("gia", "GE", "auditor"),
    строка("frozen-gia", "GE", "auditor", заморожен=True, заморожен_кем="kostya"),
)


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    журнал: dict[str, list[Any]] = {"freeze": [], "unfreeze": []}

    def freeze(login: str, *, tenant: str, only_roles: Any = None, by: Any = None) -> bool:
        журнал["freeze"].append((login, tenant, only_roles, by))
        return True

    def unfreeze(login: str, *, tenant: str, only_roles: Any = None) -> bool:
        журнал["unfreeze"].append((login, tenant, only_roles))
        return True

    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda *, tenant: tuple(r for r in ПЕРЕЧЕНЬ if tenant is None or r.tenant == tenant),
    )
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    monkeypatch.setattr(accounts, "freeze", freeze)
    monkeypatch.setattr(accounts, "unfreeze", unfreeze)
    monkeypatch.setattr(bot_links, "live_bindings", dict)
    return журнал


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def главный(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


@pytest.fixture
def админ_уК(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="admin")


@pytest.fixture
def админ_GE(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="GE", role="admin")


@pytest.fixture
def контроль(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="control")


def _заморозить(client: FlaskClient, login: str, tenant: str = "HQ") -> Any:
    return client.post("/users/freeze", data={"login": login, "tenant": tenant}, headers=ЗАГОЛОВКИ)


def _разморозить(client: FlaskClient, login: str, tenant: str = "HQ") -> Any:
    return client.post(
        "/users/unfreeze", data={"login": login, "tenant": tenant}, headers=ЗАГОЛОВКИ
    )


# --- заморозка: кто кого ---------------------------------------------------------


def test_главный_замораживает_админа_и_подписывается(
    главный: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = _заморозить(главный, "kostya")

    assert ответ.status_code == 200
    assert зовы["freeze"] == [
        ("kostya", "HQ", ("guest", "osb", "developer", "control", "admin", "superadmin"), АКТОР)
    ], "заморозка ушла без подписи «кем» или без охвата цели"


def test_главный_замораживает_другого_главного(
    главный: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    assert _заморозить(главный, "boss2").status_code == 200
    assert [x[0] for x in зовы["freeze"]] == ["boss2"]


def test_себя_заморозить_нельзя(главный: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = _заморозить(главный, ЛОГИН)

    assert ответ.status_code == 400
    assert зовы["freeze"] == []


def test_админ_уК_замораживает_своих_но_не_главного(
    админ_уК: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    assert _заморозить(админ_уК, "petr").status_code == 200
    assert _заморозить(админ_уК, "boss2").status_code == 403
    assert [x[0] for x in зовы["freeze"]] == ["petr"], "админ УК заморозил главного админа"


def test_админ_партнёра_замораживает_только_своё_пространство(
    админ_GE: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    assert _заморозить(админ_GE, "gia", "GE").status_code == 200
    assert _заморозить(админ_GE, "petr", "HQ").status_code == 403
    assert _заморозить(админ_GE, "gia", "HQ").status_code == 403, "подделка пространства"
    assert [x[0] for x in зовы["freeze"]] == ["gia"]


def test_чужой_адрес_заморозки_отказывает(главный: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = главный.post("/users/freeze", data={"login": "petr", "tenant": "HQ"})

    assert ответ.status_code == 403 and зовы["freeze"] == []


# --- разморозка: только главный админ ------------------------------------------------


def test_главный_размораживает(главный: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = _разморозить(главный, "ghost")

    assert ответ.status_code == 200
    assert зовы["unfreeze"] == [
        ("ghost", "HQ", ("guest", "osb", "developer", "control", "admin", "superadmin"))
    ]


@pytest.mark.parametrize(
    ("фикстура", "кого", "где"),
    [
        ("админ_уК", "ghost", "HQ"),
        ("админ_GE", "frozen-gia", "GE"),
        ("контроль", "ghost", "HQ"),
    ],
)
def test_кроме_главного_никто_не_размораживает(
    request: pytest.FixtureRequest,
    зовы: dict[str, list[Any]],
    фикстура: str,
    кого: str,
    где: str,
) -> None:
    client: FlaskClient = request.getfixturevalue(фикстура)

    ответ = _разморозить(client, кого, где)

    assert ответ.status_code == 403
    assert зовы["unfreeze"] == [], f"{фикстура} разморозил человека"


def test_разморозка_неизвестной_учётки_отказывает(
    главный: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    assert _разморозить(главный, "nobody").status_code == 403
    assert зовы["unfreeze"] == []


def test_чужой_адрес_разморозки_отказывает(
    главный: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = главный.post("/users/unfreeze", data={"login": "ghost", "tenant": "HQ"})

    assert ответ.status_code == 403 and зовы["unfreeze"] == []


# --- карточка -------------------------------------------------------------------------


def _карточка(client: FlaskClient, логин: str) -> str:
    return client.get(f"/administration?tab=people&off=1&person=id-{логин}").get_data(as_text=True)


def test_карточка_замороженного_называет_дату_и_кто(главный: FlaskClient) -> None:
    страница = _карточка(главный, "ghost")

    assert "Заморожен 2026-10-13, кем: boss2" in страница
    assert 'action="/users/unfreeze' in страница


def test_карточка_замороженного_без_подписи_не_выдумывает_кто(главный: FlaskClient) -> None:
    страница = _карточка(главный, "legacy")

    assert "Заморожен 2026-10-13." in страница and "кем:" not in страница


def test_админ_уК_видит_заморозку_но_не_кнопку_разморозки(админ_уК: FlaskClient) -> None:
    страница = _карточка(админ_уК, "ghost")

    assert "Заморожен 2026-10-13" in страница
    assert 'action="/users/unfreeze' not in страница
    assert "Разморозить может только главный админ" in страница


def test_у_работающего_одна_кнопка_и_это_заморозка(главный: FlaskClient) -> None:
    страница = _карточка(главный, "petr")

    assert 'action="/users/freeze' in страница
    assert "/users/disable" not in страница, "осталась вторая кнопка почти того же действия"
    assert "Да, заморозить" in страница


def test_английская_карточка_говорит_по_английски(главный: FlaskClient) -> None:
    страница = главный.get("/administration?tab=people&off=1&person=id-ghost&lang=en").get_data(
        as_text=True
    )

    assert "Frozen on 2026-10-13 by boss2" in страница
    assert "Unfreeze" in страница
