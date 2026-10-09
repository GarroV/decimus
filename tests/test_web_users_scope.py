"""#585 (D362, D364): один экран «Пользователи», охват по роли — маршруты.

Правило «кто кого» проверено само по себе (`test_web_access_policy.py`); здесь —
что каждый POST его сверяет, что поддельная форма (чужое пространство, чужой
ключ учётки, роль вне охвата) отказывает 403 и до двери базы не доходит, и что
перечень на странице отфильтрован на сервере: чужие логины и почты в ответ не
попадают вовсе.

Слой базы подменён на границе модуля; что держит сама база (последний главный
админ, условие на роль цели) — `test_db_superadmin.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, СВОЙ, войти, подменить_двери, собрать

from src.db import bot_links
from src.db.errors import AccessError
from src.web import accounts, partner_spaces

ЗАГОЛОВКИ = {"Origin": СВОЙ}


def строка(login: str, tenant: str, role: str) -> Any:
    return SimpleNamespace(
        login=login,
        role=role,
        tenant=tenant,
        email=f"{login}@mail.example",
        id=f"id-{login}",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=None,
    )


ПЕРЕЧЕНЬ = (
    строка("boss2", "HQ", "superadmin"),
    строка("kostya", "HQ", "admin"),
    строка("vika", "HQ", "control"),
    строка("petr", "HQ", "auditor"),
    строка("nino", "GE", "admin"),
    строка("gia", "GE", "auditor"),
    строка("anahit", "AM", "admin"),
    строка("aramayis", "AM", "auditor"),
)


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Двери базы на границе: перечень по пространству, запись — в журнал вызовов."""
    зовы: dict[str, list[Any]] = {
        "everyone": [],
        "add": [],
        "disable": [],
        "role": [],
        "email": [],
        "space": [],
        "countries": [],
    }

    def everyone(*, tenant: str | None) -> tuple[Any, ...]:
        зовы["everyone"].append(tenant)
        return tuple(r for r in ПЕРЕЧЕНЬ if tenant is None or r.tenant == tenant)

    def add(login: str, *, tenant: str, role: str = "auditor") -> accounts.Added:
        зовы["add"].append((login, tenant, role))
        return accounts.Added(login=login, role=role, password="одноразовый-пароль-24-знака")

    def disable(login: str, *, tenant: str, only_roles: Any = None) -> bool:
        зовы["disable"].append((login, tenant, only_roles))
        return True

    def reassign(login: str, *, tenant: str, role: str, only_roles: Any = None) -> str:
        зовы["role"].append((login, tenant, role, only_roles))
        return "auditor"

    def set_email(login: str, *, tenant: str, email: Any, only_roles: Any = None) -> bool:
        зовы["email"].append((login, tenant, email, only_roles))
        return True

    def create_space(code: str, *, name: str, countries: tuple[str, ...]) -> Any:
        зовы["space"].append((code, name, countries))
        return partner_spaces.SpaceRow(code=code, name=name, countries=countries, people=0)

    def add_countries(code: str, countries: tuple[str, ...]) -> tuple[str, ...]:
        зовы["countries"].append((code, countries))
        return countries

    monkeypatch.setattr(accounts, "everyone", everyone)
    monkeypatch.setattr(accounts, "spaces", lambda: ("AM", "GE", "HQ"))
    monkeypatch.setattr(accounts, "add", add)
    monkeypatch.setattr(accounts, "disable", disable)
    monkeypatch.setattr(accounts, "reassign_role", reassign)
    monkeypatch.setattr(accounts, "set_email", set_email)
    monkeypatch.setattr(partner_spaces, "create_partner_space", create_space)
    monkeypatch.setattr(partner_spaces, "add_countries", add_countries)
    monkeypatch.setattr(
        partner_spaces,
        "overview",
        lambda: (
            partner_spaces.SpaceRow("AM", "Партнёр А", ("AM",), 2),
            partner_spaces.SpaceRow("GE", "Партнёр Г", ("GE",), 2),
            partner_spaces.SpaceRow("HQ", "", (), 4),
        ),
    )
    monkeypatch.setattr(bot_links, "live_bindings", dict)
    return зовы


def _стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def главный(monkeypatch: pytest.MonkeyPatch, база: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="superadmin")


@pytest.fixture
def админ_уК(monkeypatch: pytest.MonkeyPatch, база: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="HQ", role="admin")


@pytest.fixture
def админ_GE(monkeypatch: pytest.MonkeyPatch, база: Any) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch, tenant="GE", role="admin")


def _записи(база: dict[str, list[Any]]) -> dict[str, list[Any]]:
    return {k: v for k, v in база.items() if k != "everyone"}


НИЧЕГО: dict[str, list[Any]] = {
    "add": [],
    "disable": [],
    "role": [],
    "email": [],
    "space": [],
    "countries": [],
}


def добавление(client: FlaskClient) -> str:
    """Форма «Новый человек» — в правой колонке экрана по `?add=1`."""
    страница = client.get("/users?add=1").get_data(as_text=True)
    return страница.split('action="/users/add')[1].split("</form>")[0]


# --- главный админ ------------------------------------------------------------


def test_главный_админ_видит_всех_и_пространства(главный: FlaskClient) -> None:
    страница = главный.get("/users").get_data(as_text=True)

    for r in ПЕРЕЧЕНЬ:
        assert r.login in страница and r.email in страница, r.login
    пространства = главный.get("/users?tab=spaces").get_data(as_text=True)
    assert 'action="/users/spaces/countries' in пространства
    новое = главный.get("/users?tab=spaces&add_space=1").get_data(as_text=True)
    assert 'action="/users/spaces/add' in новое
    форма = добавление(главный)
    assert 'value="superadmin"' in форма and 'value="admin"' in форма


def test_главный_админ_назначает_другого_главного(
    главный: FlaskClient, база: dict[str, list[Any]]
) -> None:
    ответ = главный.post(
        "/users/role",
        data={"login": "kostya", "tenant": "HQ", "role": "superadmin"},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 200
    assert база["role"] == [
        ("kostya", "HQ", "superadmin", ("auditor", "admin", "control", "superadmin"))
    ]


def test_главный_админ_заводит_админа_уК(главный: FlaskClient, база: dict[str, list[Any]]) -> None:
    ответ = главный.post(
        "/users/add", data={"login": "newdev", "tenant": "HQ", "role": "admin"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert база["add"] == [("newdev", "HQ", "admin")]


def test_последнего_главного_не_снять_сказано_словами(
    главный: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(*_a: Any, **_k: Any) -> Any:
        raise accounts.LastSuperadminError("последний")

    monkeypatch.setattr(accounts, "reassign_role", отказ)
    monkeypatch.setattr(accounts, "disable", отказ)

    роль = главный.post(
        "/users/role", data={"login": "boss2", "tenant": "HQ", "role": "admin"}, headers=ЗАГОЛОВКИ
    )
    отключение = главный.post(
        "/users/disable", data={"login": "boss2", "tenant": "HQ"}, headers=ЗАГОЛОВКИ
    )

    assert роль.status_code == 409 and "последний действующий главный" in роль.get_data(
        as_text=True
    )
    assert отключение.status_code == 409
    assert "главного админа отключить нельзя" in отключение.get_data(as_text=True)


def test_свою_роль_не_меняет_и_главный(главный: FlaskClient, база: dict[str, list[Any]]) -> None:
    ответ = главный.post(
        "/users/role", data={"login": ЛОГИН, "tenant": "HQ", "role": "admin"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert база["role"] == []


# --- админ УК -----------------------------------------------------------------


def test_админ_уК_видит_без_админов_уК(админ_уК: FlaskClient) -> None:
    страница = админ_уК.get("/users").get_data(as_text=True)

    for свой in ("vika", "petr", "nino", "gia", "anahit", "aramayis"):
        assert свой in страница and f"{свой}@mail.example" in страница, свой
    for чужое in ("boss2", "boss2@mail.example", "kostya@mail.example"):
        assert чужое not in страница, чужое
    форма = добавление(админ_уК)
    assert 'value="superadmin"' not in форма


@pytest.mark.parametrize(
    ("путь", "форма"),
    [
        ("/users/add", {"login": "x", "tenant": "HQ", "role": "admin"}),
        ("/users/add", {"login": "x", "tenant": "HQ", "role": "superadmin"}),
        ("/users/role", {"login": "petr", "tenant": "HQ", "role": "admin"}),
        ("/users/role", {"login": "petr", "tenant": "HQ", "role": "superadmin"}),
        ("/users/role", {"login": "kostya", "tenant": "HQ", "role": "auditor"}),
        ("/users/role", {"login": "boss2", "tenant": "HQ", "role": "auditor"}),
        ("/users/disable", {"login": "kostya", "tenant": "HQ"}),
        ("/users/disable", {"login": "boss2", "tenant": "HQ"}),
        ("/users/email", {"login": "kostya", "tenant": "HQ", "email": "me@evil.example"}),
        ("/users/email", {"login": "boss2", "tenant": "HQ", "email": "me@evil.example"}),
    ],
)
def test_админ_уК_не_трогает_админов_и_не_выдаёт_их(
    админ_уК: FlaskClient, база: dict[str, list[Any]], путь: str, форма: dict[str, str]
) -> None:
    ответ = админ_уК.post(путь, data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403
    assert _записи(база) == НИЧЕГО


def test_админ_уК_свою_роль_не_меняет(админ_уК: FlaskClient, база: dict[str, list[Any]]) -> None:
    ответ = админ_уК.post(
        "/users/role", data={"login": ЛОГИН, "tenant": "HQ", "role": "auditor"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400 and база["role"] == []


def test_админ_уК_заводит_пространство_и_админа_партнёра(
    админ_уК: FlaskClient, база: dict[str, list[Any]]
) -> None:
    пространство = админ_уК.post(
        "/users/spaces/add",
        data={"code": "kz", "name": "Партнёр К", "countries": "kz, uz"},
        headers=ЗАГОЛОВКИ,
    )
    человек = админ_уК.post(
        "/users/add", data={"login": "aidar", "tenant": "GE", "role": "admin"}, headers=ЗАГОЛОВКИ
    )

    assert пространство.status_code == 200 and "Пространство заведено" in пространство.get_data(
        as_text=True
    )
    assert база["space"] == [("KZ", "Партнёр К", ("KZ", "UZ"))]
    assert человек.status_code == 200 and база["add"] == [("aidar", "GE", "admin")]


def test_админ_уК_добавляет_страны(админ_уК: FlaskClient, база: dict[str, list[Any]]) -> None:
    ответ = админ_уК.post(
        "/users/spaces/countries", data={"code": "GE", "countries": "AZ"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200 and база["countries"] == [("GE", ("AZ",))]


def test_отказ_базы_на_пространстве_сказан_и_не_пятисотый(
    админ_уК: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def отказ(*_a: Any, **_k: Any) -> Any:
        raise AccessError("страна занята")

    monkeypatch.setattr(partner_spaces, "create_partner_space", отказ)
    ответ = админ_уК.post(
        "/users/spaces/add", data={"code": "KZ", "countries": "GE"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400 and "Ничего не записано" in ответ.get_data(as_text=True)


# --- админ партнёра -----------------------------------------------------------


def test_админ_партнёра_видит_только_своё_пространство(
    админ_GE: FlaskClient, база: dict[str, list[Any]]
) -> None:
    страница = админ_GE.get("/users").get_data(as_text=True)

    assert "gia" in страница and "gia@mail.example" in страница
    for чужое in ("boss2", "kostya", "vika", "petr", "anahit", "aramayis"):
        assert чужое not in страница, чужое
        assert f"{чужое}@mail.example" not in страница, чужое
    assert база["everyone"] == ["GE"]
    # Свои страны — на чтение: формы пространств нет, чужого пространства нет.
    своё = админ_GE.get("/users?tab=spaces").get_data(as_text=True)
    for вид in (страница, своё):
        assert 'action="/users/spaces' not in вид
    assert "Партнёр Г" in своё and "Партнёр А" not in своё
    форма = добавление(админ_GE)
    assert 'value="GE"' in форма
    for лишнее in ('value="HQ"', 'value="AM"', 'value="control"', 'value="superadmin"'):
        assert лишнее not in форма, лишнее


def test_админ_партнёра_ведёт_людей_своего_пространства(
    админ_GE: FlaskClient, база: dict[str, list[Any]]
) -> None:
    заведение = админ_GE.post(
        "/users/add", data={"login": "lado", "tenant": "GE", "role": "auditor"}, headers=ЗАГОЛОВКИ
    )
    роль = админ_GE.post(
        "/users/role", data={"login": "gia", "tenant": "GE", "role": "admin"}, headers=ЗАГОЛОВКИ
    )
    почта = админ_GE.post(
        "/users/email",
        data={"login": "gia", "tenant": "GE", "email": "g@x.example"},
        headers=ЗАГОЛОВКИ,
    )
    отключение = админ_GE.post(
        "/users/disable", data={"login": "gia", "tenant": "GE"}, headers=ЗАГОЛОВКИ
    )

    assert [r.status_code for r in (заведение, роль, почта, отключение)] == [200] * 4
    assert база["add"] == [("lado", "GE", "auditor")]
    assert база["role"] == [("gia", "GE", "admin", ("auditor", "admin"))]
    assert база["disable"] == [("gia", "GE", ("auditor", "admin"))]


@pytest.mark.parametrize(
    ("путь", "форма"),
    [
        # Поддельное пространство.
        ("/users/add", {"login": "x", "tenant": "AM", "role": "auditor"}),
        ("/users/add", {"login": "x", "tenant": "HQ", "role": "auditor"}),
        ("/users/add", {"login": "x", "tenant": "GE", "role": "control"}),
        ("/users/add", {"login": "x", "tenant": "GE", "role": "superadmin"}),
        # Учётка другого пространства — с её настоящим пространством и с подменой на своё.
        ("/users/disable", {"login": "aramayis", "tenant": "AM"}),
        ("/users/disable", {"login": "aramayis", "tenant": "GE"}),
        ("/users/disable", {"login": "petr", "tenant": "HQ"}),
        ("/users/role", {"login": "anahit", "tenant": "AM", "role": "auditor"}),
        ("/users/role", {"login": "gia", "tenant": "GE", "role": "superadmin"}),
        ("/users/email", {"login": "anahit", "tenant": "AM", "email": "me@evil.example"}),
        ("/users/email", {"login": "kostya", "tenant": "HQ", "email": "me@evil.example"}),
        # Пространства — не его.
        ("/users/spaces/add", {"code": "KZ", "countries": "KZ"}),
        ("/users/spaces/countries", {"code": "GE", "countries": "AZ"}),
    ],
)
def test_админ_партнёра_вне_своего_пространства_отказ(
    админ_GE: FlaskClient, база: dict[str, list[Any]], путь: str, форма: dict[str, str]
) -> None:
    ответ = админ_GE.post(путь, data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code in (400, 403), ответ.status_code
    assert ответ.status_code == 403 or форма.get("role") in ("control", "superadmin")
    assert _записи(база) == НИЧЕГО


def test_админ_партнёра_чужую_привязку_бота_не_снимает(
    админ_GE: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    отвязано: list[Any] = []
    monkeypatch.setattr(bot_links, "unbind", lambda u: отвязано.append(u) or True)

    ответ = админ_GE.post("/users/bot-unlink", data={"user_id": "id-anahit"}, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403 and отвязано == []


# --- не управляют никем -------------------------------------------------------


@pytest.mark.parametrize(("tenant", "role"), [("GE", "auditor"), ("HQ", "auditor")])
def test_сотрудник_партнёра_и_аудитор_уК_не_управляют(
    monkeypatch: pytest.MonkeyPatch, база: dict[str, list[Any]], tenant: str, role: str
) -> None:
    for client in _стенд(monkeypatch, tenant=tenant, role=role):
        страница = client.get("/users").get_data(as_text=True)
        ответы = [
            client.post(путь, data=форма, headers=ЗАГОЛОВКИ).status_code
            for путь, форма in (
                ("/users/add", {"login": "x", "tenant": tenant, "role": "auditor"}),
                ("/users/disable", {"login": "gia", "tenant": "GE"}),
                ("/users/role", {"login": "gia", "tenant": "GE", "role": "admin"}),
                ("/users/email", {"login": "gia", "tenant": "GE", "email": "a@b.example"}),
                ("/users/spaces/add", {"code": "KZ", "countries": "KZ"}),
                ("/users/spaces/countries", {"code": "GE", "countries": "AZ"}),
            )
        ]

        assert ответы == [403] * 6
        for чужое in ("gia", "nino", "petr", "@mail.example"):
            assert чужое not in страница, чужое
        assert 'action="/users/add' not in страница
    assert база["everyone"] == []
    assert _записи(база) == НИЧЕГО


def test_контроль_пространства_не_ведёт(
    monkeypatch: pytest.MonkeyPatch, база: dict[str, list[Any]]
) -> None:
    for client in _стенд(monkeypatch, tenant="HQ", role="control"):
        страница = client.get("/users").get_data(as_text=True)
        ответ = client.post(
            "/users/spaces/add", data={"code": "KZ", "countries": "KZ"}, headers=ЗАГОЛОВКИ
        )

        assert ответ.status_code == 403
        assert 'action="/users/spaces' not in страница and "Партнёр Г" not in страница
    assert _записи(база) == НИЧЕГО


def test_главный_админ_в_навигации_видит_админские_разделы(главный: FlaskClient) -> None:
    """Главный админ — админ и больше: «Методика» и «Пользователи» в навигации на месте."""
    страница = главный.get("/users").get_data(as_text=True)

    for раздел in ("/users", "/admin", "/inspections", "/actions"):
        assert f'href="{раздел}?lang=' in страница, раздел
    assert 'href="/tenants' not in страница


def test_тексты_экрана_есть_по_английски(
    monkeypatch: pytest.MonkeyPatch, база: dict[str, list[Any]]
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    with собрать(tenant="HQ", ui_lang="en").test_client() as client:
        войти(client)
        страница = client.get("/users?lang=en").get_data(as_text=True)
        страница += client.get("/users?lang=en&tab=spaces").get_data(as_text=True)

    for текст in ("Partner spaces", "Super admin", "Add countries", "Every space"):
        assert текст in страница, текст
