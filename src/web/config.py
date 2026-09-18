"""Окружение веб-админки: адрес, порт, тенант, язык интерфейса.

Тенант — обязательный параметр стенда и значения по умолчанию не имеет. Так же
устроено чтение истории (`src/db/queries.py`, T110): подстановка «default»
выглядела бы работающей ровно до второго тенанта, а потом показала бы историю
одной страны сотрудникам другой. Из веба тенант приходит один раз, из
окружения, а не из адреса: подставить его в адрес мог бы кто угодно.

Адрес прослушивания — только петля, и это проверка, а не договорённость.
Причина та же, что у MCP (`src/mcp/config.py`): площадка общая, аутентификации
у админки пока нет вовсе, а история проверок партнёров — не то, что публикуют
по недосмотру. Наружу выводит туннель, если когда-нибудь понадобится.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import WebConfigError
from .texts import default_ui_lang

WEB_HOST_VAR = "WEB_HOST"
WEB_PORT_VAR = "WEB_PORT"
WEB_TENANT_VAR = "WEB_TENANT"

DEFAULT_HOST = "127.0.0.1"
#: Следующий свободный за MCP: 8265 занимает сам сервер, 8266 — звено до него
#: (`docker-compose.yml`, сервис `link`). Номер — умолчание продукта, а не
#: рабочей копии: у копий свои диапазоны, и задаются они переменной, а не
#: правкой кода.
DEFAULT_PORT = 8267

#: Границы порта. Ниже 1024 — привилегированные, выше 65535 порта нет.
MIN_PORT = 1024
MAX_PORT = 65535


@dataclass(frozen=True)
class Settings:
    """Разобранное окружение блока."""

    host: str
    port: int
    tenant: str
    ui_lang: str


def _parse_host(raw: str) -> str:
    host = raw.strip() or DEFAULT_HOST
    if host == "localhost":
        return host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        raise WebConfigError(
            f"Адрес {WEB_HOST_VAR}={host} не петля. У админки нет аутентификации, а показывает "
            f"она историю проверок партнёров: наружу она не публикуется"
        )
    return host


def _parse_port(raw: str) -> int:
    value = raw.strip()
    if not value:
        return DEFAULT_PORT
    try:
        port = int(value)
    except ValueError:
        raise WebConfigError(f"Порт {WEB_PORT_VAR}={value} не число") from None
    if not MIN_PORT <= port <= MAX_PORT:
        raise WebConfigError(
            f"Порт {WEB_PORT_VAR}={port} вне допустимого: ожидается от {MIN_PORT} до {MAX_PORT}"
        )
    return port


def _parse_tenant(raw: str) -> str:
    tenant = raw.strip()
    if not tenant:
        raise WebConfigError(
            f"Не задана переменная окружения {WEB_TENANT_VAR}. Чью историю показывает этот "
            f"стенд — не додумывается: значения по умолчанию у тенанта нет намеренно"
        )
    return tenant


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Прочитать окружение админки. Отказ — `WebConfigError`."""
    src = os.environ if env is None else env
    return Settings(
        host=_parse_host(src.get(WEB_HOST_VAR) or ""),
        port=_parse_port(src.get(WEB_PORT_VAR) or ""),
        tenant=_parse_tenant(src.get(WEB_TENANT_VAR) or ""),
        ui_lang=default_ui_lang(src),
    )
