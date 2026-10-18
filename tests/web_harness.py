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

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient

from src.db import bot_links, journals, second_factor, web_throttle
from src.db.reach import Reach
from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.web import auth, home_board, home_ratings, home_ratings_block, to_inspect
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

    def __init__(
        self,
        login: str = ЛОГИН,
        tenant: str = "default",
        role: str | None = None,
        email: str | None = None,
        web_lang: str | None = None,
        signed_in_at: datetime | None = None,
        display_name: str | None = None,
        avatar_etag: str | None = None,
        has_second_factor: bool = True,
    ) -> None:
        self.id = "22222222-2222-2222-2222-222222222222"
        # Номер сессии (`web_sessions.id`): на него ссылаются журналы входов и действий (D462).
        self.session_id = "33333333-3333-3333-3333-333333333333"
        self.login = login
        self.tenant = tenant
        # Роль по умолчанию — рабочая роль своей стороны (D440): в УК аудитора
        # больше нет, его место занял бизнес-девелопер; у партнёра — сотрудник.
        if role is None:
            role = "developer" if canonical_tenant(tenant) == HQ_TENANT else "auditor"
        # Почта входа через Google (`web_users.email`): по умолчанию не
        # привязана — иначе вход паролем, которым входит оснастка, закрыт.
        self.email = email
        # Язык сайта из профиля (`web_users.web_lang`, 0061): по умолчанию не
        # выбран — страницы говорят языком стенда.
        self.web_lang = web_lang
        # Имя и версия фото из Google (`web_users`, 0065): по умолчанию нет —
        # блок учётки показывает логин и инициалы.
        self.display_name = display_name
        self.avatar_etag = avatar_etag
        # Вторая ступень (D463): по умолчанию подключена — админ-двойник без неё видел бы
        # только экран подключения во всех тестах разом. Наборы про ступень задают сами.
        self.has_second_factor = has_second_factor
        self.passed_second_step = True
        # Когда открыта сессия: по умолчанию только что — вход свежий, и
        # действия, требующие свежего входа (`web.reauth`), не переспрашивают.
        self.signed_in_at = signed_in_at or datetime.now(UTC)
        # Роль по умолчанию — узкая рабочая, не админ: двойник-администратор
        # прятал бы отказ раздела людей во всех тестах разом.
        self.role = role


class Сессия:
    def __init__(self, token: str = ТОКЕН) -> None:
        self.token = token
        self.session_id = "33333333-3333-3333-3333-333333333333"
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
        #: Замок вместо `pg_advisory_xact_lock`: в базе попытки по одному ключу
        #: не идут одновременно, и оснастка обязана вести себя так же — иначе
        #: набор зеленел бы на ограничителе, который параллельные попытки
        #: пропускает мимо порога (T328).
        self._замок = threading.Lock()

    @contextmanager
    def сделка(self, *, tenant: str, keys: Any) -> Iterator[web_throttle.AttemptStore]:
        """Хранилище на время одной попытки, под замком. Правило — продуктовое."""
        with self._замок:
            yield _Строки(self, tenant)

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


class _Строки:
    """Строки одного арендатора: то же, чем `web_throttle` работает в базе."""

    def __init__(self, счётчики: Счётчики, tenant: str) -> None:
        self._счётчики = счётчики
        self._tenant = tenant

    def load(self, *, scope: str, fingerprint: str) -> web_throttle.Counter | None:
        return self._счётчики.load(tenant=self._tenant, scope=scope, fingerprint=fingerprint)

    def bump(self, *, scope: str, fingerprint: str) -> web_throttle.Counter:
        return self._счётчики.bump(tenant=self._tenant, scope=scope, fingerprint=fingerprint)


def подменить_счётчики(monkeypatch: pytest.MonkeyPatch) -> Счётчики:
    """Хранилище счётчика попыток — в память, на границе модуля `web_throttle`.

    Подменяются ровно две двери: сделка на время попытки и забвение при удаче.
    Само правило (`verdict_of`, пороги, порядок «решить и записать») остаётся
    продуктовым — подменить его значило бы проверять оснастку.
    """
    счётчики = Счётчики()
    monkeypatch.setattr(web_throttle, "attempt_transaction", счётчики.сделка)
    monkeypatch.setattr(web_throttle, "load_counter", счётчики.load)
    monkeypatch.setattr(web_throttle, "forget_counter", счётчики.forget)
    return счётчики


def подменить_двери(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tenant: str,
    role: str | None = None,
    email: str | None = None,
) -> dict[str, list[Any]]:
    """Двери опознания, подменённые на границе модуля. Пишут, кого звали.

    `tenant` — пространство УЧЁТКИ, которую отдают двери при удаче: именно оно
    едет в возвращаемой `Учётка`. Тенант стенда задаёт `собрать(tenant=...)` —
    это вторая, независимая настройка: с D282 учётка любого пространства
    входит через любой стенд, и опознание своего тенанта стенда больше не
    знает вовсе.
    """
    зовы: dict[str, list[Any]] = {
        "authenticate": [],
        "open": [],
        "resolve": [],
        "close": [],
        # Журналы входов и действий (D462): что бы записали в базу.
        "login_journal": [],
        "action_journal": [],
    }

    def _authenticate(login: str, password: str) -> Учётка | None:
        зовы["authenticate"].append((login, password))
        if login == ЛОГИН and password == ПАРОЛЬ:
            return Учётка(tenant=tenant, role=role, email=email)
        return None

    def _open(account: Учётка, **origin: Any) -> Сессия:
        зовы["open"].append(account.login)
        зовы.setdefault("open_origin", []).append(origin)
        return Сессия()

    def _record_login(**запись: Any) -> None:
        зовы["login_journal"].append(запись)

    def _record_failed(**запись: Any) -> None:
        зовы["login_journal"].append({"failed": True, **запись})

    def _record_action(**запись: Any) -> None:
        зовы["action_journal"].append(запись)

    def _resolve(token: str) -> Учётка | None:
        зовы["resolve"].append((token,))
        return Учётка(tenant=tenant, role=role, email=email) if token == ТОКЕН else None

    def _close(token: str) -> bool:
        зовы["close"].append(token)
        return True

    monkeypatch.setattr(auth, "authenticate", _authenticate)
    monkeypatch.setattr(auth, "open_session", _open)
    monkeypatch.setattr(auth, "resolve_session", _resolve)
    monkeypatch.setattr(auth, "close_session", _close)
    # Журналы пишут в базу; наборы экранов её не поднимают и записи собирают в списки.
    monkeypatch.setattr(journals, "record_login", _record_login)
    monkeypatch.setattr(journals, "record_failed_login", _record_failed)
    monkeypatch.setattr(journals, "record_action", _record_action)
    # Охват вошедшего (волна 1, #340) у партнёра читает его страны из базы.
    # Экранные наборы базы не поднимают, поэтому дверь охвата подменена так
    # же, как двери опознания: УК — вся сеть, партнёр — его же код страны.
    monkeypatch.setattr(auth, "reach_of", охват_без_базы)
    # Сверка номера аккаунта Google (F-027) пишет в базу; экранные наборы её не
    # поднимают — аккаунт всегда «тот же». Наборы про сверку подменяют сами.
    monkeypatch.setattr(auth, "claim_google_sub", lambda _email, _subject, **_k: "ok")
    # Вторая ступень (D463): наборы экранов её не поднимают — способа входа ни у кого нет,
    # сессия выдаётся сразу. Наборы про ступень (`test_web_second_step`) ходят в настоящую базу.
    monkeypatch.setattr(second_factor, "has_any", lambda _user_id: False)
    # Привязка бота (D286) на вкладке «Пользователи» тоже читает базу: по
    # умолчанию бот не привязан ни у кого. Наборы про привязку подменяют сами.
    monkeypatch.setattr(bot_links, "binding_of", lambda _user_id: None)
    monkeypatch.setattr(bot_links, "live_bindings", lambda: {})
    # «Главная» (D378) читает рейтинги и счётчики доски, «Проверки» — «Где нужно
    # проверить» (D418): по умолчанию пусто. Наборы про эти блоки подменяют сами.
    monkeypatch.setattr(to_inspect, "load", lambda **_: to_inspect.Block())
    monkeypatch.setattr(home_ratings, "load_latest", lambda *_, **__: {})
    monkeypatch.setattr(home_ratings_block, "load", lambda **_: home_ratings_block.Block())
    monkeypatch.setattr(home_board, "load_counts", lambda *_, **__: home_board.Counts())
    # Ограничитель перебора (T325) стоит на том же пути, что и вход, и без
    # хранилища пошёл бы в настоящую базу на КАЖДОЙ отправке формы — то есть
    # уронил бы все экранные наборы разом.
    подменить_счётчики(monkeypatch)
    return зовы


def охват_без_базы(tenant: str) -> Reach:
    """Охват пространства без похода в базу: УК — всё, партнёр — страна его кода."""
    код = canonical_tenant(tenant)
    if код == HQ_TENANT:
        return Reach(код, None, None)
    return Reach(код, None, (код,))


def собрать(
    *,
    tenant: str,
    ui_lang: str = "ru",
    bot_username: str | None = None,
    admin_public_url: str | None = None,
    mcp_public_url: str | None = None,
    trusted_proxies: int | None = None,
    webauthn_rp_id: str | None = None,
    webauthn_origin: str | None = None,
    demo: bool = False,
) -> Flask:
    """Приложение с настройками стенда набора. Публичные адреса включают OAuth (D417)."""
    app = create_app(
        Settings(
            host="127.0.0.1",
            port=8266,
            tenant=tenant,
            ui_lang=ui_lang,
            secret_key=СЕКРЕТ,
            bot_username=bot_username,
            admin_public_url=admin_public_url,
            mcp_public_url=mcp_public_url,
            webauthn_rp_id=webauthn_rp_id,
            webauthn_origin=webauthn_origin,
            demo=demo,
            **({} if trusted_proxies is None else {"trusted_proxies": trusted_proxies}),
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
