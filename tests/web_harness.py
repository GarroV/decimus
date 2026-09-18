"""Оснастка экранных наборов блока `web`: приложение и вошедший человек.

Общая, а не своя у каждого набора: после T323 ни одна страница админки не
открывается без опознания, то есть вход нужен КАЖДОМУ экранному тесту. Две
копии этой оснастки разошлись бы на первой же правке входа, и разошлись бы
молча — набор экранов остался бы зелёным, проверяя вход, которого уже нет.

Двери опознания подменяются на границе модуля `src/web/auth.py`, как двери
блока `db` подменяются на границе `src/web/inspections.py`. База здесь не
поднимается: живой путь до Postgres проверяет `tests/test_db_web_access.py`.

Вход делается НАСТОЯЩЕЙ отправкой формы, а не подставленной в браузер кукой:
кука подписана, и подложить её мимо формы означало бы проверять экраны в
состоянии, которого у живого приложения не бывает.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from src.web import auth
from src.web.app import create_app
from src.web.config import Settings

#: Ключ подписи набора. Не секрет: он живёт ровно один прогон и ничего, кроме
#: куки этого же прогона, не подписывает.
СЕКРЕТ = "ключ-подписи-куки-этого-набора-длиннее-тридцати-двух"

ЛОГИН = "director"
ПАРОЛЬ = "верный-пароль"
ТОКЕН = "сессионный-токен"
СВОЙ = "http://localhost"


class Учётка:
    """То немногое, что страницам нужно знать о вошедшем."""

    def __init__(self, login: str = ЛОГИН, tenant: str = "default") -> None:
        self.id = "22222222-2222-2222-2222-222222222222"
        self.login = login
        self.tenant = tenant


class Сессия:
    def __init__(self, token: str = ТОКЕН) -> None:
        self.token = token
        # Срок, который админка кладёт в куку. Настоящий, а не «через год»:
        # просроченный здесь закрыл бы вход всему набору.
        self.expires_at = datetime.now(UTC) + timedelta(hours=12)


def подменить_двери(monkeypatch: pytest.MonkeyPatch, *, tenant: str) -> dict[str, list[Any]]:
    """Двери опознания, подменённые на границе модуля. Пишут, кого звали."""
    зовы: dict[str, list[Any]] = {"authenticate": [], "open": [], "resolve": [], "close": []}

    def _authenticate(login: str, password: str, *, tenant: str) -> Учётка | None:
        зовы["authenticate"].append((login, password, tenant))
        if login == ЛОГИН and password == ПАРОЛЬ:
            return Учётка(tenant=tenant)
        return None

    def _open(account: Учётка) -> Сессия:
        зовы["open"].append(account.login)
        return Сессия()

    def _resolve(token: str, *, tenant: str) -> Учётка | None:
        зовы["resolve"].append((token, tenant))
        return Учётка(tenant=tenant) if token == ТОКЕН else None

    def _close(token: str) -> bool:
        зовы["close"].append(token)
        return True

    monkeypatch.setattr(auth, "authenticate", _authenticate)
    monkeypatch.setattr(auth, "open_session", _open)
    monkeypatch.setattr(auth, "resolve_session", _resolve)
    monkeypatch.setattr(auth, "close_session", _close)
    return зовы


def собрать(*, tenant: str, ui_lang: str = "ru") -> Flask:
    """Приложение с настройками стенда набора."""
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant=tenant,
            ui_lang=ui_lang,
            secret_key=СЕКРЕТ,
        )
    )
    app.config.update(TESTING=True)
    return app


def войти(client: FlaskClient, *, login: str = ЛОГИН, password: str = ПАРОЛЬ) -> Any:
    """Отправить форму входа так, как это делает браузер."""
    return client.post(
        auth.LOGIN_PATH,
        data={"login": login, "password": password},
        headers={"Origin": СВОЙ},
    )
