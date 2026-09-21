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

import pytest
from flask.testing import FlaskClient
from web_harness import ЛОГИН, войти, подменить_двери, собрать

from src.web import accounts

ТЕНАНТ = "demo"
#: Свой источник: проверка происхождения формы отвергает чужой 403-м, и без
#: этого заголовка тест проверял бы её вместо заслона по роли.
СВОЙ = {"Origin": "http://localhost"}


def строка(login: str, *, role: str = "auditor", disabled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        login=login,
        role=role,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        disabled_at=datetime(2026, 9, 10, tzinfo=UTC) if disabled else None,
    )


@pytest.fixture
def стенд_админа(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="admin")
    monkeypatch.setattr(
        accounts, "everyone", lambda **_: (строка(ЛОГИН, role="admin"), строка("petr"))
    )
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


@pytest.fixture
def стенд_аудитора(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="auditor")
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def test_аудитора_в_раздел_людей_не_пускают(стенд_аудитора: FlaskClient) -> None:
    ответ = стенд_аудитора.get("/users")

    # 403, а не 404: человек вошёл, он здесь свой, и «страницы нет» вместо
    # «вам сюда нельзя» отправило бы его чинить несломанное.
    assert ответ.status_code == 403
    assert "не для всех" in ответ.get_data(as_text=True)


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

    ответ = стенд_админа.post("/users/add", data={"login": "petr", "role": "auditor"}, headers=СВОЙ)

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

    ответ = стенд_админа.post("/users/disable", data={"login": "petr"}, headers=СВОЙ)

    assert ответ.status_code == 200
    assert отключённые == ["petr"]
