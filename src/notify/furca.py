"""Канал FURCA: одна отправка сообщения владельцу (D438, D439, D641).

`POST {FURCA_NOTIFY_URL}/notify` с ключом `FURCA_SECRET` в заголовке `Authorization: Bearer`,
тело — `{"project": "decimus", "kind": "alert" | "done", "text": "…"}`; канал доводит текст до
владельца в Telegram. Ответ `401` — неверный ключ, `400` — негодный вид: оба приходят
исключением `urllib.error.HTTPError`. Переменные не заданы — канала нет, `channel` отдаёт `None`
и вызывающий ничего не шлёт.

Общий для всех тревог продукта: суточный сбор агрегаторов (`src/ratings/aggregators/alert.py`),
загрузка обучения, оповещения о смене состояния подключений (`src/health/alerts.py`). Решение,
писать ли и что, — у вызывающего; здесь только адрес и отправка.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.request
from collections.abc import Mapping
from urllib.parse import urlsplit

URL_VAR = "FURCA_NOTIFY_URL"
SECRET_VAR = "FURCA_SECRET"  # noqa: S105 — имя переменной, не значение
PROJECT = "decimus"
TIMEOUT_SEC = 15

#: Виды сообщения канала: сломалось и починилось.
ALERT = "alert"
DONE = "done"


def _is_internal_host(host: str) -> bool:
    """Внутреннее имя: localhost, имя без точки (сеть docker) или локальный адрес."""
    if host == "localhost" or "." not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False  # имя с точкой — публичное
    return address.is_loopback or address.is_private


def channel(env: Mapping[str, str]) -> tuple[str, str] | None:
    """Адрес `/notify` канала и ключ; чего-то нет — уведомление выключено.

    `http://` годится только для внутреннего имени (localhost, имя без точки);
    внешний хост по открытому http — тоже выключено, нужен https.
    """
    base = (env.get(URL_VAR) or "").strip().rstrip("/")
    secret = (env.get(SECRET_VAR) or "").strip()
    if not base.startswith(("http://", "https://")) or not secret:
        return None
    # Ключ канала уходит заголовком: по открытому http через интернет он ушёл бы
    # читаемым. http — только для внутренних имён, иначе https обязателен.
    if base.startswith("http://") and not _is_internal_host(urlsplit(base).hostname or ""):
        return None
    return f"{base}/notify", secret


def send(target: tuple[str, str], text: str, kind: str = ALERT) -> None:
    """Отправить сообщение в канал; ошибка сети или канала — исключение вызывающему."""
    url, secret = target
    request = urllib.request.Request(  # noqa: S310 — адрес из окружения площадки
        url,
        data=json.dumps({"project": PROJECT, "kind": kind, "text": text}).encode(),
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
        response.read()
