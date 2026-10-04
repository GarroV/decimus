"""#399 (часть): админ УК задаёт человеку почту для входа через Google и роль — с экрана.

Раньше почта привязывалась только командой (`tools/web_user.py email`). Права
— ядро: ошибка здесь не кричит, она молча раздаёт админов или открывает вход
через Google чужой почте. Поэтому проверяется прежде всего, КОГО экран
пускает к двери базы, и что он ей передаёт.

Админ партнёра людьми не управляет вовсе — D288 открыт; здесь это
закреплено, а не расширено. Слой базы подменён на границе: его права —
`test_db_web_access.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, СВОЙ, войти, подменить_двери, собрать

from src.db.errors import EmailTakenError
from src.web import accounts

ЗАГОЛОВКИ = {"Origin": СВОЙ}


def строка(login: str, *, tenant: str = "HQ", role: str = "auditor", email: Any = None) -> Any:
    return SimpleNamespace(
        login=login,
        role=role,
        tenant=tenant,
        email=email,
        id=f"id-{login}",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=None,
    )


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    позвали: dict[str, list[Any]] = {"role": [], "email": []}

    def _роль(login: str, *, tenant: str, role: str) -> bool:
        позвали["role"].append((login, tenant, role))
        return login != "nobody"

    def _почта(login: str, *, tenant: str, email: str | None) -> bool:
        позвали["email"].append((login, tenant, email))
        if email == "taken@dodobrands.io":
            raise EmailTakenError("занята")
        return login != "nobody"

    monkeypatch.setattr(accounts, "set_role", _роль)
    monkeypatch.setattr(accounts, "set_email", _почта)
    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda **_: (
            строка(ЛОГИН, role="admin"),
            строка("petr", email="petr@dodobrands.io"),
            строка("nino", tenant="GE"),
        ),
    )
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    return позвали


def стенд(monkeypatch: pytest.MonkeyPatch, *, tenant: str, role: str) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role=role)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def админ_ук(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from стенд(monkeypatch, tenant="HQ", role="admin")


def test_админ_уК_видит_почту_и_формы_правки(админ_ук: FlaskClient) -> None:
    страница = админ_ук.get("/users").get_data(as_text=True)

    assert "petr@dodobrands.io" in страница
    assert 'action="/users/role' in страница and 'action="/users/email' in страница


def test_админ_уК_назначает_роль(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = админ_ук.post(
        "/users/role", data={"login": "petr", "tenant": "HQ", "role": "admin"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert "Роль изменена" in ответ.get_data(as_text=True)
    assert зовы["role"] == [("petr", "HQ", "admin")]


def test_админ_уК_правит_человека_партнёра_в_его_пространстве(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """Как заведение и отключение: админ УК управляет людьми всех пространств."""
    админ_ук.post(
        "/users/email",
        data={"login": "nino", "tenant": "GE", "email": "nino@partner.ge"},
        headers=ЗАГОЛОВКИ,
    )

    assert зовы["email"] == [("nino", "GE", "nino@partner.ge")]


def test_админ_уК_привязывает_почту(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = админ_ук.post(
        "/users/email",
        data={"login": "petr", "tenant": "HQ", "email": " Petr@Dodobrands.io "},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 200
    assert "Почта сохранена" in ответ.get_data(as_text=True)
    assert зовы["email"] == [("petr", "HQ", "Petr@Dodobrands.io")]


def test_пустая_почта_снимает_вход_через_google(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = админ_ук.post(
        "/users/email", data={"login": "petr", "tenant": "HQ", "email": "  "}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert "Почта снята" in ответ.get_data(as_text=True)
    assert зовы["email"] == [("petr", "HQ", None)]


def test_занятая_почта_названа_прямо(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = админ_ук.post(
        "/users/email",
        data={"login": "petr", "tenant": "HQ", "email": "taken@dodobrands.io"},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 409
    assert "уже привязана" in ответ.get_data(as_text=True)


def test_не_почта_до_базы_не_доходит(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = админ_ук.post(
        "/users/email", data={"login": "petr", "tenant": "HQ", "email": "petr"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert зовы["email"] == []


def test_незаведённая_роль_до_базы_не_доходит(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    ответ = админ_ук.post(
        "/users/role", data={"login": "petr", "tenant": "HQ", "role": "owner"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert зовы["role"] == []


def test_незаведённое_пространство_до_базы_не_доходит(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    for путь, поле in (("/users/role", ("role", "admin")), ("/users/email", ("email", "a@b.c"))):
        ответ = админ_ук.post(
            путь, data={"login": "petr", "tenant": "XX", поле[0]: поле[1]}, headers=ЗАГОЛОВКИ
        )
        assert ответ.status_code == 400

    assert зовы == {"role": [], "email": []}


def test_свою_роль_не_снять(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    """Снять с себя админа — закрыть экран людей себе, а на стенде с одним админом — всем."""
    ответ = админ_ук.post(
        "/users/role", data={"login": ЛОГИН, "tenant": "HQ", "role": "auditor"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert зовы["role"] == []


def test_нет_такой_учётки_сказано(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = админ_ук.post(
        "/users/role", data={"login": "nobody", "tenant": "HQ", "role": "admin"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert "не найдена" in ответ.get_data(as_text=True)


@pytest.mark.parametrize(
    ("tenant", "role"), [("HQ", "auditor"), ("GE", "admin"), ("GE", "auditor")]
)
def test_кроме_админа_уК_никто_не_правит_даже_прямой_отправкой(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]], tenant: str, role: str
) -> None:
    """Админ партнёра тоже: его права над людьми не решены (D288)."""
    for client in стенд(monkeypatch, tenant=tenant, role=role):
        роль = client.post(
            "/users/role",
            data={"login": "petr", "tenant": tenant, "role": "admin"},
            headers=ЗАГОЛОВКИ,
        )
        почта = client.post(
            "/users/email",
            data={"login": "petr", "tenant": tenant, "email": "me@evil.example"},
            headers=ЗАГОЛОВКИ,
        )
        страница = client.get("/users").get_data(as_text=True)

        assert (роль.status_code, почта.status_code) == (403, 403)
        assert 'action="/users/role' not in страница and 'action="/users/email' not in страница
    assert зовы == {"role": [], "email": []}


def test_чужая_страница_не_правит(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    for путь, поле in (("/users/role", ("role", "admin")), ("/users/email", ("email", "a@b.c"))):
        ответ = админ_ук.post(
            путь,
            data={"login": "petr", "tenant": "HQ", поле[0]: поле[1]},
            headers={"Origin": "https://evil.example"},
        )
        assert ответ.status_code == 403

    assert зовы == {"role": [], "email": []}


def test_тексты_правки_есть_по_английски(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> None:
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ", ui_lang="en").test_client() as client:
        войти(client)
        ответ = client.post(
            "/users/email?lang=en",
            data={"login": "petr", "tenant": "HQ", "email": "petr@dodobrands.io"},
            headers=ЗАГОЛОВКИ,
        )

    assert "Email saved" in ответ.get_data(as_text=True)
    assert "Google sign-in email" in ответ.get_data(as_text=True)
