"""Доезжают ли до приложения заголовки звена, когда оно объявлено своим.

Набор поднимает НАСТОЯЩИЙ `waitress` и ходит к нему по сети, а не тестовым
клиентом Flask. Иначе проверять нечего: тестовый клиент передаёт заголовки
как есть, и дыра, из-за которой они не доезжали, в нём не воспроизводится
вовсе — ровно поэтому она и прожила до публикации наружу (#306).

Что именно было сломано: `WEB_TRUSTED_PROXIES` читался и проверялся, но в
`serve()` не уходил, а `waitress` без названного доверенного звена режет
`X-Forwarded-*` на входе. Заслон происхождения считал запрос пришедшим по
HTTP и отвечал 403 на каждую отправку формы за туннелем; счётчик перебора
видел один адрес на всех пришедших снаружи.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from waitress import serve

from src.web.__main__ import _proxy_options
from src.web.config import Settings

КЛЮЧ = "ключ-подписи-длиной-не-меньше-тридцати-двух-знаков"


def настройки(*, звенья: int) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=_свободный_порт(),
        tenant="demo",
        ui_lang="ru",
        secret_key=КЛЮЧ,
        trusted_proxies=звенья,
    )


def _свободный_порт() -> int:
    """Порт, который сейчас никем не занят.

    Прибитый номер сделал бы набор непрогоняемым рядом с поднятым стендом —
    а стенд на машине разработчика поднят как раз тогда, когда эти проверки
    и нужны.
    """
    with socket.socket() as гнездо:
        гнездо.bind(("127.0.0.1", 0))
        return int(гнездо.getsockname()[1])


def приложение_эхо(окружение: dict[str, Any], ответ: Any) -> list[bytes]:
    """Возвращает ровно то, что увидел из заголовков звена.

    Настоящее приложение здесь не нужно и мешало бы: оно требует базы, а
    вопрос набора — доехали ли заголовки до WSGI вообще.
    """
    схема = окружение.get("HTTP_X_FORWARDED_PROTO", "нет")
    цепочка = окружение.get("HTTP_X_FORWARDED_FOR", "нет")
    ответ("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return [f"{схема}|{цепочка}".encode()]


@pytest.fixture
def поднятый_сервер() -> Iterator[Any]:
    """Поднимает сервер на время одной проверки и гасит его после."""
    запущенные: list[Any] = []

    def поднять(settings: Settings) -> str:
        поток = threading.Thread(
            target=serve,
            args=(приложение_эхо,),
            kwargs={
                "host": settings.host,
                "port": settings.port,
                "ident": "decimus-test",
                **_proxy_options(settings),
            },
            daemon=True,
        )
        поток.start()
        запущенные.append(поток)
        _дождаться_порта(settings.host, settings.port)
        return f"http://{settings.host}:{settings.port}/"

    yield поднять


def _дождаться_порта(хост: str, порт: int, попыток: int = 50) -> None:
    for _ in range(попыток):
        try:
            with socket.create_connection((хост, порт), timeout=0.1):
                return
        except OSError:
            continue
    raise AssertionError(f"сервер не поднялся на {хост}:{порт}")


def _спросить(адрес: str) -> str:
    import urllib.request

    запрос = urllib.request.Request(  # noqa: S310 -- свой же адрес, поднятый этим же набором
        адрес,
        headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.7"},
    )
    with urllib.request.urlopen(запрос, timeout=5) as ответ:  # noqa: S310 -- свой же адрес
        return ответ.read().decode()


def test_заголовки_звена_доезжают_когда_звено_объявлено(поднятый_сервер: Any) -> None:
    адрес = поднятый_сервер(настройки(звенья=1))

    увиденное = _спросить(адрес)

    assert увиденное == "https|203.0.113.7"


def test_заголовки_звена_режутся_когда_звена_нет(поднятый_сервер: Any) -> None:
    """Умолчание — не верить: без объявленного звена заголовки посторонние.

    Обратная сторона той же настройки, и проверяется она здесь потому, что
    именно её нарушение раздало бы перебирающему бесконечный запас адресов.
    """
    адрес = поднятый_сервер(настройки(звенья=0))

    увиденное = _спросить(адрес)

    assert увиденное == "нет|нет"
