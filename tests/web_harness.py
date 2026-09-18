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

from src.db import web_throttle
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


class Счётчики:
    """Хранилище счётчика попыток в памяти набора — вместо таблицы (T325).

    Подменяется ТОЛЬКО хранилище, а правило «после скольких неудач и
    насколько» остаётся продуктовым (`web_throttle.verdict_of`). Подменить
    заодно и правило значило бы проверять оснастку: набор зеленел бы на любом
    ограничителе, включая снятый.

    Часы не подменяются: чтобы проверить, что запрет кончается, набор отматывает
    время самих строк (`отмотать`) — так же, как тест базы отматывает
    `updated_at` запросом.
    """

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], web_throttle.Counter] = {}

    def load(self, *, tenant: str, scope: str, fingerprint: str) -> web_throttle.Counter | None:
        return self.rows.get((tenant, scope, fingerprint))

    def bump(self, *, tenant: str, scope: str, fingerprint: str) -> web_throttle.Counter:
        сейчас = datetime.now(UTC)
        было = self.rows.get((tenant, scope, fingerprint))
        забыт = было is None or было.updated_at < сейчас - web_throttle.FORGET_AFTER
        стало = web_throttle.Counter(
            failures=1 if забыт or было is None else было.failures + 1, updated_at=сейчас
        )
        self.rows[(tenant, scope, fingerprint)] = стало
        return стало

    def forget(self, *, tenant: str, scope: str, fingerprint: str) -> None:
        self.rows.pop((tenant, scope, fingerprint), None)

    def отмотать(self, назад: timedelta) -> None:
        """Сдвинуть все строки в прошлое: «прошло столько времени»."""
        self.rows = {
            ключ: web_throttle.Counter(
                failures=строка.failures, updated_at=строка.updated_at - назад
            )
            for ключ, строка in self.rows.items()
        }


def подменить_счётчики(monkeypatch: pytest.MonkeyPatch) -> Счётчики:
    """Хранилище счётчика попыток — в память, на границе модуля `web_throttle`."""
    счётчики = Счётчики()
    monkeypatch.setattr(web_throttle, "load_counter", счётчики.load)
    monkeypatch.setattr(web_throttle, "bump_counter", счётчики.bump)
    monkeypatch.setattr(web_throttle, "forget_counter", счётчики.forget)
    return счётчики


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
    # Ограничитель перебора (T325) стоит на том же пути, что и вход, и без
    # хранилища пошёл бы в настоящую базу на КАЖДОЙ отправке формы — то есть
    # уронил бы все экранные наборы разом.
    подменить_счётчики(monkeypatch)
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
