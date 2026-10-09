"""Мини-апп обхода — свой сервис, админка только передаёт ему запросы.

Право записи в идущие проверки есть только у сервиса обхода: его контейнер
держит том состояния на запись, админка — `:ro`. Поэтому здесь держится
граница: сервис обхода не отвечает ничем, кроме адресов обхода, а админка
адресов записи сама не обслуживает — только передаёт.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from test_web_walk import АУДИТОР, ТОКЕН, подписать
from test_web_walk_write import JPEG
from web_harness import СЕКРЕТ
from werkzeug.serving import BaseWSGIServer, make_server

from src.db.bot_links import NEVER_BOUND
from src.domain import get_state, start_inspection
from src.web import walk, walk_access, walk_proxy, walk_write
from src.web.app import create_app
from src.web.config import Settings
from src.web.walk_app import create_walk_app
from src.web.walk_auth import ENDPOINTS, INIT_DATA_HEADER


def _настройки(**сверх: object) -> Settings:
    поля: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 8266,
        "tenant": "default",
        "ui_lang": "ru",
        "secret_key": СЕКРЕТ,
    }
    return Settings(**(поля | сверх))  # type: ignore[arg-type]


def _маршруты(app: Flask) -> dict[str, object]:
    return {rule.endpoint: app.view_functions[rule.endpoint] for rule in app.url_map.iter_rules()}


@pytest.fixture
def сервис_обхода(
    domain_env: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[str, BaseWSGIServer]]:
    """Настоящий сервис обхода на свободном порту петли — как контейнер `walk`."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", ТОКЕН)
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", str(АУДИТОР))
    monkeypatch.delenv("WEB_WALK_PREVIEW_CHAT", raising=False)
    monkeypatch.setattr(walk.queries, "previous_findings", lambda **_: None)
    monkeypatch.setattr(walk_access.bot_links, "standing", lambda _: NEVER_BOUND)
    start_inspection(АУДИТОР, unit="Белград-1", kind="planned", report_lang="ru", ui_lang="ru")
    сервер = make_server("127.0.0.1", 0, create_walk_app(_настройки()), threaded=True)
    поток = threading.Thread(target=сервер.serve_forever, daemon=True)
    поток.start()
    try:
        yield f"http://127.0.0.1:{сервер.server_port}", сервер
    finally:
        сервер.shutdown()
        поток.join(timeout=5)


def test_сервис_обхода_не_отвечает_ничем_кроме_обхода(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", ТОКЕН)
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", str(АУДИТОР))

    маршруты = set(_маршруты(create_walk_app(_настройки())))

    assert маршруты == ENDPOINTS | {"static"}, "в сервис с правом записи попала админка"


def test_админка_без_адреса_сервиса_обхода_не_отдаёт(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", ТОКЕН)
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", str(АУДИТОР))

    app = create_app(_настройки())

    assert not set(_маршруты(app)) & ENDPOINTS
    # Неизвестный адрес у админки уводит на вход — страницы обхода тут нет.
    assert app.test_client().get(walk.PAGE_PATH).status_code in (302, 404)


def test_админка_сама_не_пишет_а_передаёт(monkeypatch: pytest.MonkeyPatch) -> None:
    """Каждый адрес обхода в админке — передача сервису, а не запись на месте."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", ТОКЕН)
    monkeypatch.setenv("ALLOWED_TELEGRAM_IDS", str(АУДИТОР))

    маршруты = _маршруты(create_app(_настройки(walk_upstream="http://walk:8269")))

    for имя in ENDPOINTS:
        функция = маршруты[имя]
        assert getattr(функция, "__module__", "") == walk_proxy.__name__, имя


def test_запись_через_админку_доходит_до_сервиса_обхода(
    сервис_обхода: tuple[str, BaseWSGIServer],
) -> None:
    адрес, _ = сервис_обхода
    админка = create_app(_настройки(walk_upstream=адрес)).test_client()
    подпись = {INIT_DATA_HEADER: подписать(АУДИТОР)}

    кадр = админка.post(
        walk_write.PHOTO_PATH, data=JPEG, content_type="image/jpeg", headers=подпись
    )
    assert кадр.status_code == 201, кадр.get_data(as_text=True)
    ref = кадр.get_json()["ref"]
    запись = админка.post(
        walk_write.FINDING_PATH,
        json={"op": "add", "zone": "hot_kitchen", "code": "CLN05", "level": "D1", "photos": [ref]},
        headers=подпись,
    )

    assert запись.status_code == 200, запись.get_data(as_text=True)
    assert запись.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors https://web.telegram.org" in запись.headers["Content-Security-Policy"]
    проверка = get_state(АУДИТОР)
    assert проверка is not None and [f.code for f in проверка.findings] == ["CLN05"]


def test_отказ_сервиса_обхода_доходит_как_есть(сервис_обхода: tuple[str, BaseWSGIServer]) -> None:
    адрес, _ = сервис_обхода
    админка = create_app(_настройки(walk_upstream=адрес)).test_client()

    ответ = админка.post(walk.DATA_PATH, data="подделка", content_type="text/plain")

    assert ответ.status_code == 401
    assert ответ.get_json() == {"error": "unauthorized"}


def test_сервис_обхода_молчит_экран_получает_503_словами() -> None:
    # Порт 9 на петле никто не слушает: соединение отклоняется сразу.
    админка = create_app(_настройки(walk_upstream="http://127.0.0.1:9")).test_client()

    ответ = админка.post(walk.DATA_PATH, data="x", content_type="text/plain")

    assert ответ.status_code == 503
    тело = ответ.get_json()
    assert тело["error"] == "unavailable" and тело["texts"]
