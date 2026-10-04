"""#324: человек меняет свой пароль с экрана — путь формы целиком.

Слой базы подменён на границе (`accounts.change_own_password`): его свойства —
своя строка, прежний хеш, закрытие чужих сессий — проверяет
`test_db_web_own_password.py` на настоящей базе. Здесь вопрос другой: что
форма пропускает к базе, что отвечает человеку и что ограничитель перебора
стоит и на этой двери (текущий пароль подбирается так же, как на входе).

Хранилище счётчика подменено (`web_harness.Счётчики`), правило — продуктовое.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from web_harness import ПАРОЛЬ, СВОЙ, ТОКЕН, войти, подменить_двери, собрать

from src.db.errors import AccessError
from src.db.web_access import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from src.db.web_throttle import FAILURES_BEFORE_LOCK
from src.web import accounts
from src.web.app import MAX_BODY_BYTES

ТЕНАНТ = "HQ"
ПУТЬ = "/users/password"
НОВЫЙ = "новый-пароль-длиннее-порога"
НЕ_ТОТ = "не-тот-текущий-пароль"


@pytest.fixture
def зовы(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Дверь базы: верен только `ПАРОЛЬ`, короткий новый — отказ, как у настоящей."""
    позвали: list[tuple[str, str, str]] = []

    def _сменить(token: str, *, current: str, new: str) -> bool:
        позвали.append((token, current, new))
        if len(new) < MIN_PASSWORD_LENGTH:
            raise AccessError("короткий")
        return current == ПАРОЛЬ

    monkeypatch.setattr(accounts, "change_own_password", _сменить)
    return позвали


@pytest.fixture
def стенд(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="auditor")
    with собрать(tenant=ТЕНАНТ).test_client() as client:
        assert войти(client).status_code == 302
        yield client


def сменить(
    стенд: FlaskClient, *, current: str = ПАРОЛЬ, new: str = НОВЫЙ, repeat: str | None = None
) -> Any:
    return стенд.post(
        ПУТЬ,
        data={"current": current, "new": new, "repeat": new if repeat is None else repeat},
        headers={"Origin": СВОЙ},
    )


def test_форма_смены_видна_каждому_вошедшему(стенд: FlaskClient) -> None:
    страница = стенд.get("/users").get_data(as_text=True)

    assert f'action="{ПУТЬ}' in страница
    assert 'name="current"' in страница and 'name="repeat"' in страница


def test_верный_текущий_меняет_пароль_своей_сессией(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    ответ = стенд.post(
        ПУТЬ,
        data={"current": ПАРОЛЬ, "new": НОВЫЙ, "repeat": НОВЫЙ, "token": "чужой-токен"},
        headers={"Origin": СВОЙ},
    )

    assert ответ.status_code == 200
    assert "Пароль сменён" in ответ.get_data(as_text=True)
    # Токен — из куки этого запроса, а не из формы: чужой токен сюда не подать.
    assert зовы == [(ТОКЕН, ПАРОЛЬ, НОВЫЙ)]


def test_неверный_текущий_отказ_без_подробностей(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    ответ = сменить(стенд, current=НЕ_ТОТ)

    assert ответ.status_code == 400
    страница = ответ.get_data(as_text=True)
    assert "Пароль не сменён" in страница
    assert "Пароль сменён." not in страница
    # Введённое обратно в разметку не возвращается: среди него пароли.
    assert НЕ_ТОТ not in страница and НОВЫЙ not in страница


def test_несовпадение_с_повтором_до_базы_не_доходит(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    ответ = сменить(стенд, repeat=НОВЫЙ + "x")

    assert ответ.status_code == 400
    assert "не совпадает" in ответ.get_data(as_text=True)
    assert зовы == []


def test_короткий_новый_до_базы_не_доходит(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    короткий = "к" * (MIN_PASSWORD_LENGTH - 1)

    ответ = сменить(стенд, new=короткий)

    assert ответ.status_code == 400
    assert str(MIN_PASSWORD_LENGTH) in ответ.get_data(as_text=True)
    assert зовы == []


def test_длинный_новый_до_базы_не_доходит(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    ответ = сменить(стенд, new="д" * (MAX_PASSWORD_LENGTH + 1))

    assert ответ.status_code == 400
    assert str(MAX_PASSWORD_LENGTH) in ответ.get_data(as_text=True)
    assert зовы == []


def test_длинный_текущий_до_базы_не_доходит(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    """Такого текущего нет ни у кого: ответ тот же, что на неверный, но без scrypt."""
    ответ = сменить(стенд, current="д" * (MAX_PASSWORD_LENGTH + 1))

    assert ответ.status_code == 400
    assert "проверьте текущий пароль" in ответ.get_data(as_text=True)
    assert зовы == []


def test_тело_больше_предела_отвергается_до_разбора(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    # Тело чуть больше нашего предела, но меньше предела Werkzeug на память
    # формы (500 КБ): иначе 413 дал бы он, а не `MAX_BODY_BYTES`. Поле `new`
    # уходит в форму дважды (с повтором), поэтому каждое — половина с запасом.
    половина = "x" * (MAX_BODY_BYTES // 2 + 1024)
    ответ = сменить(стенд, new=половина)

    assert ответ.status_code == 413
    assert зовы == []


def test_перебор_текущего_пароля_запирается(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    """Текущий пароль подбирается через форму профиля так же, как через вход."""
    порог = FAILURES_BEFORE_LOCK["login"]
    for _ in range(порог):
        сменить(стенд, current=НЕ_ТОТ)
    дошло = len(зовы)

    ответ = сменить(стенд, current=ПАРОЛЬ)

    assert ответ.status_code == 429
    assert ответ.headers.get("Retry-After")
    # Запертый не доходит до сверки — ни верным паролем, ни неверным.
    assert len(зовы) == дошло


def test_удачная_смена_сбрасывает_счётчик(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    порог = FAILURES_BEFORE_LOCK["login"]
    for _ in range(порог - 1):
        сменить(стенд, current=НЕ_ТОТ)
    assert сменить(стенд).status_code == 200

    assert сменить(стенд, current=НЕ_ТОТ).status_code == 400


def test_чужая_страница_пароль_не_меняет(
    стенд: FlaskClient, зовы: list[tuple[str, str, str]]
) -> None:
    ответ = стенд.post(
        ПУТЬ,
        data={"current": ПАРОЛЬ, "new": НОВЫЙ, "repeat": НОВЫЙ},
        headers={"Origin": "https://evil.example"},
    )

    assert ответ.status_code == 403
    assert зовы == []


def test_тексты_есть_по_английски(monkeypatch: pytest.MonkeyPatch, зовы: Any) -> None:
    подменить_двери(monkeypatch, tenant=ТЕНАНТ, role="auditor")
    with собрать(tenant=ТЕНАНТ, ui_lang="en").test_client() as client:
        войти(client)
        страница = client.get("/users?lang=en").get_data(as_text=True)
        ответ = client.post(
            ПУТЬ + "?lang=en",
            data={"current": ПАРОЛЬ, "new": НОВЫЙ, "repeat": НОВЫЙ},
            headers={"Origin": СВОЙ},
        )

    assert "Change password" in страница
    assert "Password changed" in ответ.get_data(as_text=True)
