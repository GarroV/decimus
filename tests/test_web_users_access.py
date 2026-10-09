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

import logging
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

    def _роль(login: str, *, tenant: str, role: str, only_roles: Any = None) -> str | None:
        позвали["role"].append((login, tenant, role))
        return None if login == "nobody" else "auditor"

    def _почта(login: str, *, tenant: str, email: str | None, only_roles: Any = None) -> bool:
        позвали["email"].append((login, tenant, email))
        if email == "taken@dodobrands.io":
            raise EmailTakenError("занята")
        return login != "nobody"

    monkeypatch.setattr(accounts, "reassign_role", _роль)
    monkeypatch.setattr(accounts, "set_email", _почта)
    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda **_: (
            строка(ЛОГИН, role="admin"),
            строка("petr", email="petr@dodobrands.io"),
            строка("nino", tenant="GE"),
            # Тёзка в другом пространстве — для проверки «свой = пара».
            строка(ЛОГИН, tenant="GE"),
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
    """Аудитора — в контроль: роль из охвата админа УК (D364)."""
    ответ = админ_ук.post(
        "/users/role", data={"login": "petr", "tenant": "HQ", "role": "control"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert "Роль изменена" in ответ.get_data(as_text=True)
    assert зовы["role"] == [("petr", "HQ", "control")]


def test_админ_уК_правит_человека_партнёра_в_его_пространстве(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """Админ УК ведёт людей партнёров (D364)."""
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
    """Цель ищется по базе (#585): в незаведённом пространстве её нет — 403, как чужая."""
    for путь, поле in (("/users/role", ("role", "auditor")), ("/users/email", ("email", "a@b.c"))):
        ответ = админ_ук.post(
            путь, data={"login": "petr", "tenant": "XX", поле[0]: поле[1]}, headers=ЗАГОЛОВКИ
        )
        assert ответ.status_code == 403

    assert зовы == {"role": [], "email": []}


def test_свою_роль_не_снять(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    """Снять с себя админа — закрыть экран людей себе, а на стенде с одним админом — всем."""
    ответ = админ_ук.post(
        "/users/role", data={"login": ЛОГИН, "tenant": "HQ", "role": "auditor"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert зовы["role"] == []


def test_свою_роль_не_снять_и_другим_регистром_логина(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """Логин хранится в нижнем регистре: «Director» — та же учётка, что «director»."""
    ответ = админ_ук.post(
        "/users/role",
        data={"login": ЛОГИН.upper(), "tenant": "HQ", "role": "auditor"},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 400
    assert зовы["role"] == []


def test_тот_же_логин_в_другом_пространстве_не_свой(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """«Свой» — пара (пространство, логин), а не логин: тёзка в GE — другой человек."""
    ответ = админ_ук.post(
        "/users/role", data={"login": ЛОГИН, "tenant": "GE", "role": "auditor"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert зовы["role"] == [(ЛОГИН, "GE", "auditor")]


def test_нет_такой_учётки_неотличимо_от_чужой(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """#585: «нет такой» и «не ваша» снаружи неразличимы — обе 403, до двери базы."""
    ответ = админ_ук.post(
        "/users/role",
        data={"login": "nobody", "tenant": "HQ", "role": "auditor"},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 403
    assert зовы["role"] == []


def test_учётка_пропавшая_между_чтением_и_записью_сказано(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Дверь базы не нашла цель (сменилась роль или отключили) — «не найдена», не успех."""
    monkeypatch.setattr(accounts, "reassign_role", lambda *_a, **_k: None)
    ответ = админ_ук.post(
        "/users/role", data={"login": "petr", "tenant": "HQ", "role": "control"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert "не найдена" in ответ.get_data(as_text=True)


@pytest.mark.parametrize(("tenant", "role"), [("HQ", "auditor"), ("GE", "auditor")])
def test_аудитор_и_сотрудник_партнёра_не_правят_даже_прямой_отправкой(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]], tenant: str, role: str
) -> None:
    """Аудитор УК и сотрудник партнёра людьми не управляют (D346, D364).

    Админ партнёра с #585 ведёт людей своего пространства —
    `test_web_users_scope.py`.
    """
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


def test_смена_роли_оставляет_след_в_журнале(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """След без новой таблицы: кто правил, кого, было → стало (ревью безопасности, M3)."""
    with caplog.at_level(logging.INFO, logger="src.web.people"):
        админ_ук.post(
            "/users/role",
            data={"login": "nino", "tenant": "GE", "role": "admin"},
            headers=ЗАГОЛОВКИ,
        )

    след = [з.getMessage() for з in caplog.records if з.name == "src.web.people"]
    assert len(след) == 1, след
    assert all(часть in след[0] for часть in (f"HQ/{ЛОГИН}", "GE/nino", "auditor", "admin"))


def test_смена_почты_оставляет_след_без_адреса(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """Факт смены почты — да, сам адрес — нет: журнал приложения не место для почт."""
    with caplog.at_level(logging.INFO, logger="src.web.people"):
        админ_ук.post(
            "/users/email",
            data={"login": "petr", "tenant": "HQ", "email": "new.petr@dodobrands.io"},
            headers=ЗАГОЛОВКИ,
        )
        админ_ук.post(
            "/users/email", data={"login": "petr", "tenant": "HQ", "email": ""}, headers=ЗАГОЛОВКИ
        )

    след = [з.getMessage() for з in caplog.records if з.name == "src.web.people"]
    assert len(след) == 2, след
    assert all(f"HQ/{ЛОГИН}" in з and "HQ/petr" in з for з in след)
    assert not any("@" in з for з in след)


def test_отказ_правки_следа_не_оставляет(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """След — о сделанном: отказ формы или «нет такой учётки» правкой не был."""
    with caplog.at_level(logging.INFO, logger="src.web.people"):
        админ_ук.post(
            "/users/role",
            data={"login": "nobody", "tenant": "HQ", "role": "admin"},
            headers=ЗАГОЛОВКИ,
        )
        админ_ук.post(
            "/users/email",
            data={"login": "petr", "tenant": "HQ", "email": "petr"},
            headers=ЗАГОЛОВКИ,
        )
        админ_ук.post(
            "/users/email",
            data={"login": "nobody", "tenant": "HQ", "email": "nobody@dodobrands.io"},
            headers=ЗАГОЛОВКИ,
        )

    assert not [з for з in caplog.records if з.name == "src.web.people"]


def test_контроль_вне_уК_до_базы_не_доходит(
    админ_ук: FlaskClient, зовы: dict[str, list[Any]]
) -> None:
    """Роль «контроль» у партнёра — отказ 400 на экране, а не 503 «база отказала»."""
    ответ = админ_ук.post(
        "/users/role", data={"login": "nino", "tenant": "GE", "role": "control"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert зовы["role"] == []


def test_контроль_в_уК_назначается(админ_ук: FlaskClient, зовы: dict[str, list[Any]]) -> None:
    ответ = админ_ук.post(
        "/users/role", data={"login": "petr", "tenant": "HQ", "role": "control"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert зовы["role"] == [("petr", "HQ", "control")]


def test_экран_предлагает_контроль_только_людям_уК(админ_ук: FlaskClient) -> None:
    страница = админ_ук.get("/users").get_data(as_text=True)
    строки = [r.split("</tr>")[0] for r in страница.split("<tr")]
    ук = next(r for r in строки if "petr" in r and 'name="role"' in r)
    партнёр = next(r for r in строки if "nino" in r and 'name="role"' in r)

    assert 'value="control"' in ук
    assert 'value="control"' not in партнёр


def test_добавить_контроль_партнёру_отказ_до_базы(
    админ_ук: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def завести(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("до базы дойти не должно")

    monkeypatch.setattr(accounts, "add", завести)
    ответ = админ_ук.post(
        "/users/add",
        data={"login": "ctl", "tenant": "GE", "role": "control"},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 400
    assert "только в пространстве УК" in ответ.get_data(as_text=True)


@pytest.fixture
def контроль(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    yield from стенд(monkeypatch, tenant="HQ", role="control")


@pytest.mark.parametrize(
    ("путь", "форма"),
    [
        ("/users/role", {"login": "petr", "tenant": "HQ", "role": "admin"}),
        ("/users/add", {"login": "zed", "tenant": "HQ", "role": "auditor"}),
        ("/users/disable", {"login": "petr", "tenant": "HQ"}),
        ("/admin/publish", {}),
        ("/admin/items", {"code": "X1"}),
        ("/admin/items/X1", {"name_ru": "x", "name_en": "x"}),
        ("/admin/items/X1/disable", {}),
        ("/admin/items/X1/restore", {}),
        ("/admin/zones", {"code": "Z1", "name_ru": "x", "name_en": "x"}),
        ("/admin/zones/shares", {}),
        ("/admin/zones/Z1/rename", {"name_ru": "x", "name_en": "x"}),
        ("/admin/zones/Z1/remove", {}),
        ("/admin/route", {}),
        ("/admin/scoring", {}),
        ("/admin/checklists", {"code": "c1"}),
        ("/admin/checklists/c1/state", {"state": "active"}),
        ("/admin/checklists/c1/apply", {}),
        ("/admin/bot/c1", {}),
        ("/inspections/x/retract", {"reason": "дубль"}),
    ],
)
def test_контроль_вне_рейтингов_не_пишет(
    контроль: FlaskClient, зовы: dict[str, list[Any]], путь: str, форма: dict[str, str]
) -> None:
    """Методика, люди и проверки — на чтение: заслон `before_request`, не каждый маршрут.

    Заслон `_install_control_gate` — единственная защита методических POST
    (`/admin/*`): маршрутной проверки роли у них нет. `/users/role` и retract
    закрыты ещё и маршрутом; `/users/add` и `/users/disable` заслон пропускает
    (D360), и чужую роль или человека отсекает маршрут (`_people_scope`).
    """
    ответ = контроль.post(путь, data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403
    assert зовы == {"role": [], "email": []}


@pytest.mark.parametrize("путь", ["/country", "/admin", "/actions", "/calendar", "/tenants"])
def test_контроль_не_видит_разделов_кроме_своих(контроль: FlaskClient, путь: str) -> None:
    """D358, D366: кроме обзора, проверок, рейтингов и своих людей — не открывается."""
    assert контроль.get(путь).status_code == 404


@pytest.mark.parametrize("путь", ["/overview", "/inspections"])
def test_контроль_читает_обзор_и_проверки(контроль: FlaskClient, путь: str) -> None:
    """D366: контролинг видит обзор и все проверки — заслон пропускает (без базы стенда — 503)."""
    assert контроль.get(путь).status_code not in (403, 404)


@pytest.mark.parametrize("путь", ["/inspections/x/retract", "/inspections/x/letter/save"])
def test_контроль_в_проверках_не_пишет(контроль: FlaskClient, путь: str) -> None:
    assert контроль.post(путь, data={}, headers=ЗАГОЛОВКИ).status_code == 403


def test_контроль_видит_рейтинги_и_свои_дела(контроль: FlaskClient) -> None:
    assert контроль.get("/users").status_code == 200
    вход = контроль.get("/")
    assert вход.status_code == 302 and вход.headers["Location"].endswith("/ratings")


def test_контроль_в_навигации_только_свои_разделы(контроль: FlaskClient) -> None:
    страница = контроль.get("/users").get_data(as_text=True)
    for свой in ("/overview", "/inspections", "/ratings"):
        assert f'href="{свой}?lang=' in страница, свой
    for чужой in ("/admin", "/actions", "/country"):
        assert f'href="{чужой}?lang=' not in страница, чужой


def test_контроль_выходит_сам(контроль: FlaskClient) -> None:
    assert контроль.post("/logout", headers=ЗАГОЛОВКИ).status_code == 302


# --- D360: контроль сам заводит людей контролинга -------------------------
# Права — ядро: экран прячет чужие формы, но довод здесь — ответ на ПОДДЕЛАННУЮ
# отправку. Контроль трогает только учётки роли «контроль» в УК; чужая роль,
# чужое пространство, чужой человек — отказ до двери базы.


@pytest.fixture
def люди_контроля(
    monkeypatch: pytest.MonkeyPatch, зовы: dict[str, list[Any]]
) -> dict[str, list[Any]]:
    """Перечень с людьми контролинга; заведение и отключение пишут, кого звали."""
    зовы["add"] = []
    зовы["disable"] = []

    def _завести(login: str, *, tenant: str, role: str = "auditor") -> accounts.Added:
        зовы["add"].append((login, tenant, role))
        return accounts.Added(login=login, role=role, password="одноразовый-пароль-24-знака")

    def _отключить(login: str, *, tenant: str, only_roles: Any = None) -> bool:
        зовы["disable"].append((login, tenant))
        return True

    monkeypatch.setattr(accounts, "add", _завести)
    monkeypatch.setattr(accounts, "disable", _отключить)
    monkeypatch.setattr(
        accounts,
        "everyone",
        lambda **_: (
            строка(ЛОГИН, role="control", email="director@dodobrands.io"),
            строка("vika", role="control", email="vika@dodobrands.io"),
            строка("boss", role="admin", email="boss@dodobrands.io"),
            строка("petr", email="petr@dodobrands.io"),
            строка("nino", tenant="GE", email="nino@partner.ge"),
        ),
    )
    return зовы


def test_контроль_заводит_контроль_в_уК(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    ответ = контроль.post(
        "/users/add", data={"login": "olga", "tenant": "HQ", "role": "control"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert "одноразовый-пароль-24-знака" in ответ.get_data(as_text=True)
    assert люди_контроля["add"] == [("olga", "HQ", "control")]


@pytest.mark.parametrize(
    "форма",
    [
        {"login": "olga", "tenant": "HQ", "role": "admin"},
        {"login": "olga", "tenant": "HQ", "role": "auditor"},
        {"login": "olga", "tenant": "GE", "role": "control"},
        {"login": "olga", "tenant": "GE", "role": "admin"},
        {"login": "olga", "tenant": "HQ"},
    ],
)
def test_контроль_не_заводит_чужую_роль_и_пространство(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]], форма: dict[str, str]
) -> None:
    ответ = контроль.post("/users/add", data=форма, headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 403
    assert люди_контроля["add"] == []


@pytest.mark.parametrize(
    ("логин", "пространство"),
    [("petr", "HQ"), ("boss", "HQ"), ("nino", "GE"), ("vika", "GE"), ("ghost", "HQ")],
)
def test_контроль_не_трогает_чужих_людей(
    контроль: FlaskClient,
    люди_контроля: dict[str, list[Any]],
    логин: str,
    пространство: str,
) -> None:
    """Аудитор, админ, партнёр, чужое пространство, незнакомец — отказ до базы."""
    почта = контроль.post(
        "/users/email",
        data={"login": логин, "tenant": пространство, "email": "me@evil.example"},
        headers=ЗАГОЛОВКИ,
    )
    отключение = контроль.post(
        "/users/disable", data={"login": логин, "tenant": пространство}, headers=ЗАГОЛОВКИ
    )

    assert (почта.status_code, отключение.status_code) == (403, 403)
    assert люди_контроля["email"] == [] and люди_контроля["disable"] == []


def test_контроль_задаёт_почту_контролю(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    ответ = контроль.post(
        "/users/email",
        data={"login": "vika", "tenant": "HQ", "email": "v.new@dodobrands.io"},
        headers=ЗАГОЛОВКИ,
    )

    assert ответ.status_code == 200
    assert люди_контроля["email"] == [("vika", "HQ", "v.new@dodobrands.io")]


def test_контроль_отключает_контроль(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    ответ = контроль.post(
        "/users/disable", data={"login": "vika", "tenant": "HQ"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 200
    assert люди_контроля["disable"] == [("vika", "HQ")]


def test_контроль_не_отключает_себя(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    """То же правило, что у админа: отключить себя — выйти и не вернуться."""
    ответ = контроль.post(
        "/users/disable", data={"login": ЛОГИН, "tenant": "HQ"}, headers=ЗАГОЛОВКИ
    )

    assert ответ.status_code == 400
    assert люди_контроля["disable"] == []


def test_контроль_не_меняет_роли_даже_своим(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    for роль in ("control", "admin"):
        ответ = контроль.post(
            "/users/role", data={"login": "vika", "tenant": "HQ", "role": роль}, headers=ЗАГОЛОВКИ
        )
        assert ответ.status_code == 403
    assert люди_контроля["role"] == []


def test_контроль_видит_только_людей_контролинга(
    контроль: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    страница = контроль.get("/users").get_data(as_text=True)

    assert "vika" in страница and "vika@dodobrands.io" in страница
    for чужое in ("petr", "boss", "nino", "petr@dodobrands.io", "boss@dodobrands.io"):
        assert чужое not in страница, чужое
    assert 'action="/users/role' not in страница
    assert 'action="/users/add' in страница and 'action="/users/disable' in страница
    форма = страница.split('action="/users/add')[1].split("</form>")[0]
    assert 'value="control"' in форма and 'value="HQ"' in форма
    for лишнее in ('value="admin"', 'value="auditor"', 'value="GE"'):
        assert лишнее not in форма, лишнее


def test_админ_уК_видит_всех_при_людях_контролинга(
    админ_ук: FlaskClient, люди_контроля: dict[str, list[Any]]
) -> None:
    """Админ УК видит людей УК, кроме админов, и партнёров (D364): админ «boss» — вне охвата."""
    страница = админ_ук.get("/users").get_data(as_text=True)

    for свой in ("vika", "petr", "nino", "petr@dodobrands.io"):
        assert свой in страница, свой
    for чужое in ("boss", "boss@dodobrands.io"):
        assert чужое not in страница, чужое
    assert 'action="/users/role' in страница
