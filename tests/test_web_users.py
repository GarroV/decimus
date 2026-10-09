"""T338 (#322): люди проекта заводятся с экрана, а не из командной строки.

Проверяется главное свойство раздела: он ЗАКРЫТ. Заведение переехало туда,
куда ходят все, кому открыли админку, и без заслона аудитор, заглянувший
посмотреть свою проверку, мог бы завести себе вторую учётку или отключить
чужую. Ошибка такого рода не видна ничем: доступ выглядит как доступ.

Слой базы здесь подменён намеренно — его собственные проверки живут в
`test_db_web_access.py` и ходят в настоящую базу. Здесь вопрос другой: кого
экран пускает и что он показывает.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.web import accounts
from src.web.accounts import everyone as настоящий_перечень

#: Админ УК: управлять людьми может только он (D288).
ТЕНАНТ = "HQ"
#: Свой источник: проверка происхождения формы отвергает чужой 403-м, и без
#: этого заголовка тест проверял бы её вместо заслона по роли.
СВОЙ = {"Origin": "http://localhost"}


def строка(login: str, *, role: str = "auditor", disabled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        login=login,
        role=role,
        tenant=ТЕНАНТ,
        id=f"id-{login}",
        email=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=datetime(2026, 9, 10, tzinfo=UTC) if disabled else None,
    )


@pytest.fixture
def стенд_админа(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="admin")
    monkeypatch.setattr(
        accounts, "everyone", lambda **_: (строка(ЛОГИН, role="admin"), строка("petr"))
    )
    monkeypatch.setattr(accounts, "spaces", lambda: (ТЕНАНТ, "GE"))
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def стенд_аудитора(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="auditor")
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_аудитор_видит_на_вкладке_только_себя(стенд_аудитора: FlaskClient) -> None:
    """Вкладка открыта всем ради привязки бота (D286), людьми управляет админ УК (D288)."""
    ответ = стенд_аудитора.get("/users")

    assert ответ.status_code == 200
    страница = ответ.get_data(as_text=True)
    assert ЛОГИН in страница
    assert "/users/add" not in страница and "/users/disable" not in страница


def test_аудитор_не_заводит_людей_даже_прямой_отправкой(
    стенд_аудитора: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    заведённые: list[str] = []
    monkeypatch.setattr(
        accounts,
        "add",
        lambda login, **_: заведённые.append(login),  # type: ignore[func-returns-value]
    )

    ответ = стенд_аудитора.post(
        "/users/add", data={"login": "chuzhoy", "role": "admin"}, headers=СВОЙ
    )

    # Заслон стоит на ДЕЙСТВИИ, а не на ссылке: спрятанная кнопка не мешает
    # отправить форму руками, и проверка только на GET была бы украшением.
    assert ответ.status_code == 403
    assert заведённые == []


def test_админ_видит_живых_и_отключённых(стенд_админа: FlaskClient) -> None:
    страница = стенд_админа.get("/users").get_data(as_text=True)

    assert "petr" in страница
    # Отключённые не прячутся: вопрос «у кого был доступ» задают после
    # инцидента, и пустое место на него не отвечает.
    assert "Завести человека" in страница


def test_пароль_заведённого_показан_один_раз_и_не_уходит_в_адрес(
    стенд_админа: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        accounts,
        "add",
        lambda login, **_: accounts.Added(login=login, role="auditor", password="СЕКРЕТ-РОВНО-РАЗ"),
    )

    ответ = стенд_админа.post(
        "/users/add", data={"login": "petr", "role": "auditor", "tenant": ТЕНАНТ}, headers=СВОЙ
    )

    # Страница, а не перенаправление: пароль в адресе остался бы в истории
    # браузера и в журнале обратного прокси, то есть перестал бы быть паролем
    # ровно в момент показа.
    assert ответ.status_code == 200
    assert "СЕКРЕТ-РОВНО-РАЗ" in ответ.get_data(as_text=True)
    assert ответ.headers.get("Location") is None


def test_себя_отключить_нельзя(стенд_админа: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
    отключённые: list[str] = []
    monkeypatch.setattr(
        accounts,
        "disable",
        lambda login, **_: отключённые.append(login) or True,  # type: ignore[func-returns-value]
    )

    ответ = стенд_админа.post("/users/disable", data={"login": ЛОГИН}, headers=СВОЙ)

    # Отключить себя — это выход без возврата, а на стенде с одним
    # администратором ещё и закрытый навсегда экран людей: снять пометку
    # изнутри продукта нечем.
    assert ответ.status_code == 400
    assert отключённые == []


def test_отключение_чужой_учётки_доходит_до_базы(
    стенд_админа: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    отключённые: list[str] = []

    def _disable(login: str, **_: object) -> bool:
        отключённые.append(login)
        return True

    monkeypatch.setattr(accounts, "disable", _disable)

    ответ = стенд_админа.post(
        "/users/disable", data={"login": "petr", "tenant": ТЕНАНТ}, headers=СВОЙ
    )

    assert ответ.status_code == 200
    assert отключённые == ["petr"]


# --- пространства (волна 1, #340; D282, D286, D288) ------------------------


def test_сотрудник_партнёра_не_заводит_людей(monkeypatch: pytest.MonkeyPatch) -> None:
    """D346: сотрудник партнёра не администрирует. Админ партнёра — `test_web_users_scope.py`."""
    заведено: list[Any] = []
    monkeypatch.setattr(accounts, "add", lambda *a, **k: заведено.append(k))
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    подменить_двери(monkeypatch, tenant="GE", role="auditor")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/add", headers=СВОЙ, data={"login": "x", "tenant": "GE"})
        отключение = client.post(
            "/users/disable", headers=СВОЙ, data={"login": "x", "tenant": "GE"}
        )
    assert ответ.status_code == 403 and заведено == []
    assert отключение.status_code == 403


def test_админ_уК_заводит_человека_в_выбранное_пространство(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    заведено: list[Any] = []

    def завести(login: str, **k: Any) -> accounts.Added:
        заведено.append((login, k["tenant"]))
        return accounts.Added(login=login, role=k.get("role", "auditor"), password="p")

    monkeypatch.setattr(accounts, "add", завести)
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    monkeypatch.setattr(accounts, "everyone", lambda **_k: ())
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        client.post("/users/add", headers=СВОЙ, data={"login": "ge-director", "tenant": "GE"})
    assert заведено == [("ge-director", "GE")]


def test_незаведённое_пространство_в_форме_это_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    заведено: list[Any] = []
    monkeypatch.setattr(accounts, "add", lambda *a, **k: заведено.append(k))
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    monkeypatch.setattr(accounts, "everyone", lambda **_k: ())
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.post("/users/add", headers=СВОЙ, data={"login": "x", "tenant": "ZZ"})
    assert ответ.status_code == 400 and заведено == []


def test_админ_уК_видит_людей_всех_пространств(monkeypatch: pytest.MonkeyPatch) -> None:
    спросили: list[Any] = []

    def все(**k: Any) -> tuple[Any, ...]:
        спросили.append(k)
        return ()

    monkeypatch.setattr(accounts, "everyone", все)
    monkeypatch.setattr(accounts, "spaces", lambda: ("HQ", "GE"))
    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        assert client.get("/users").status_code == 200
    assert спросили == [{"tenant": None}]


def test_не_админ_видит_только_себя(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        accounts, "everyone", lambda **k: pytest.fail("перечень людей отдан не-админу")
    )
    подменить_двери(monkeypatch, tenant="GE", role="auditor")
    with собрать(tenant="HQ").test_client() as client:
        войти(client)
        ответ = client.get("/users")
    assert ответ.status_code == 200
    страница = ответ.get_data(as_text=True)
    assert ЛОГИН in страница and "/users/add" not in страница


def test_расхождение_баз_на_вкладке_не_раскрывает_стенд(
    стенд_админа: FlaskClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """#515: вошедший не видит базы, хосты и роли; оператор находит их в журнале."""
    # Arrange — настоящий перечень людей, подключение истории ведёт в другую базу
    monkeypatch.setattr(accounts, "everyone", настоящий_перечень)
    monkeypatch.setenv("DATABASE_URL", "postgresql://dodo_audit_app:x@db.example/stand")
    monkeypatch.setenv(
        "DATABASE_RETRACTION_URL", "postgresql://dodo_audit_admin:x@db.example/shared"
    )
    monkeypatch.delenv("DATABASE_ADMIN_URL", raising=False)

    # Act
    with caplog.at_level("ERROR"):
        страница = стенд_админа.get("/users").get_data(as_text=True)

    # Assert
    for деталь in ("db.example", "shared", "dodo_audit_admin", "DATABASE_RETRACTION_URL"):
        assert деталь not in страница, деталь
    журнал = " ".join(r.getMessage() for r in caplog.records if r.levelname == "ERROR")
    assert "shared" in журнал
    assert "db.example" in журнал
