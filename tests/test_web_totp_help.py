"""Справка «как пользоваться приложением-аутентификатором» на экране «Вход и защита».

Без базы: статус способов подменён на границе `store`, страница настоящая. Проверяется, что под
«?» у заголовка блока есть шаги и что названия кнопок в них — настоящие тексты кнопок на том же
языке. Сломанная копия: убрать `info_tip(...)` из `settings/security.html` — тест падает.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from flask.testing import FlaskClient
from web_harness import войти, подменить_двери, собрать

from src.db import second_factor as store

ЗАЩИТА = "/settings/security"
СПРАВКА = {
    "ru": ("Подключить (один раз):", "Подключить приложение", "Подтвердить и подключить"),
    "en": ("Connect (once):", "Connect an app", "Confirm and connect"),
}


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    статус = SimpleNamespace(
        passkeys=(), totp_confirmed=False, totp_pending=False, backup_left=0, has_factor=False
    )
    monkeypatch.setattr(store, "status_of", lambda _user: статус)
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        yield c


@pytest.mark.parametrize("язык", ["ru", "en"])
def test_справка_под_значком_есть_на_обоих_языках(клиент: FlaskClient, язык: str) -> None:
    страница = клиент.get(f"{ЗАЩИТА}?lang={язык}").get_data(as_text=True)

    заголовок, кнопка_старт, кнопка_подтвердить = СПРАВКА[язык]
    assert 'id="info-totp"' in страница
    assert заголовок in страница
    # Названия кнопок в шагах — те же, что на самих кнопках блока.
    assert f"{кнопка_старт}</button>" in страница
    assert f"«{кнопка_старт}»" in страница or f"“{кнопка_старт}”" in страница
    assert f"«{кнопка_подтвердить}»" in страница or f"“{кнопка_подтвердить}”" in страница
