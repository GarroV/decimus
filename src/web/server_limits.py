"""Явные пределы сервера `waitress` и предел одновременных медленных запросов.

Умолчания `waitress` (4 потока, тело до 1 ГиБ, обрыв молчащего соединения через
120 с) подходят случайно, а не по расчёту, поэтому здесь они названы. Аудит
12.10 (F-121), подробности — advisory GHSA-7gm6-hc9m-w3vc.

**Потоки.** Админка и сервис обхода — по 8. Память не ограничивает: поток —
это мегабайты, а тела свыше порога `waitress` пишет во временный файл, а не
держит в памяти. Ограничивает пул соединений с базой (`DB_POOL_MAX`, docs/08):
лишний поток ждёт соединения, а не падает, так что прибавка потоков на базу не
давит, а страницам без базы даёт место.

**Тело запроса.** Самая большая законная загрузка по умолчанию — пачка кадров
одной записи: `MAX_PHOTOS_PER_FINDING` × `MAX_UPLOAD_BYTES` = 100 МиБ. Поверх —
запас на рамки формы; вложение предписания может быть больше, если владелец
поднял `ATTACHMENT_MAX_MB`, и предел сервера поднимается следом. Каждый адрес
дальше режет своим, более узким пределом (`request.max_content_length`); этот —
внешний потолок, а не замена им.

**Медленный путь отдельно от остального.** Запрос обхода через админку и вызов
модели внутри обхода держат поток десятки секунд. Пока их число не ограничено,
несколько таких запросов занимают все потоки, и страница входа не открывается.
`SlowGate` пускает не больше названного числа и отказывает остальным сразу —
503 за миллисекунды вместо ожидания потока.
"""

from __future__ import annotations

import functools
import os
import threading
from collections.abc import Mapping
from typing import Any

from src.db.config import MAX_ATTACHMENT_MB, load_action_plan_settings
from src.db.errors import ConfigError
from src.db.imports import MAX_PHOTOS_PER_FINDING
from src.domain.uploads import MAX_UPLOAD_BYTES

from .errors import WebConfigError

WEB_THREADS_VAR = "WEB_THREADS"
WEB_CONNECTION_LIMIT_VAR = "WEB_CONNECTION_LIMIT"
WEB_CHANNEL_TIMEOUT_VAR = "WEB_CHANNEL_TIMEOUT_SEC"
WEB_MAX_BODY_MB_VAR = "WEB_MAX_BODY_MB"
WEB_WALK_PROXY_MAX_VAR = "WEB_WALK_PROXY_MAX"
WALK_MODEL_MAX_VAR = "WALK_MODEL_MAX_CONCURRENT"

DEFAULT_THREADS = 8
DEFAULT_CONNECTION_LIMIT = 100
#: Молчащее соединение держит слот; кадр с мобильной сети идёт кусками, и
#: каждый кусок обнуляет срок, так что 60 с — это «замолчал», а не «медленный».
DEFAULT_CHANNEL_TIMEOUT_SEC = 60
_MB = 1024 * 1024
#: Запас сверх тела: рамки формы и заголовки частей.
BODY_OVERHEAD_BYTES = 1 * _MB
#: Через админку одновременно проходит не больше стольких запросов к обходу:
#: половина потоков (`DEFAULT_THREADS`) остаётся страницам админки.
DEFAULT_WALK_PROXY_MAX = 4
#: Вызовов модели в сервисе обхода одновременно: меньше потоков обхода, чтобы
#: сохранение находок и кадров не вставало за подбором.
DEFAULT_WALK_MODEL_MAX = 3

MAX_THREADS = 64
MAX_CONNECTION_LIMIT = 1000
MAX_CHANNEL_TIMEOUT_SEC = 600
MAX_SLOTS = 64


def _int(env: Mapping[str, str], name: str, default: int, *, low: int, high: int) -> int:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise WebConfigError(f"{name}={raw!r}: нужно целое число") from None
    if not low <= value <= high:
        raise WebConfigError(f"{name}={value}: допустимо от {low} до {high}")
    return value


def default_max_body_bytes(env: Mapping[str, str] | None = None) -> int:
    """Потолок тела по умолчанию: пачка кадров или вложение предписания, что больше."""
    frames = MAX_UPLOAD_BYTES * MAX_PHOTOS_PER_FINDING
    try:
        attachment = load_action_plan_settings(env).max_bytes
    except ConfigError:
        # Мусор в ATTACHMENT_MAX_MB — отказ самого запуска (`load_action_plan_settings`
        # зовётся при сборке приложения), здесь он предел сервера не определяет.
        attachment = 0
    return max(frames, attachment) + BODY_OVERHEAD_BYTES


def server_options(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Аргументы `waitress.serve` с названными пределами. Мусор в окружении — `WebConfigError`."""
    src = os.environ if env is None else env
    if (src.get(WEB_MAX_BODY_MB_VAR) or "").strip():
        body = _int(src, WEB_MAX_BODY_MB_VAR, 0, low=1, high=MAX_ATTACHMENT_MB * 2) * _MB
    else:
        body = default_max_body_bytes(src)
    return {
        "threads": _int(src, WEB_THREADS_VAR, DEFAULT_THREADS, low=2, high=MAX_THREADS),
        "connection_limit": _int(
            src,
            WEB_CONNECTION_LIMIT_VAR,
            DEFAULT_CONNECTION_LIMIT,
            low=1,
            high=MAX_CONNECTION_LIMIT,
        ),
        "channel_timeout": _int(
            src,
            WEB_CHANNEL_TIMEOUT_VAR,
            DEFAULT_CHANNEL_TIMEOUT_SEC,
            low=5,
            high=MAX_CHANNEL_TIMEOUT_SEC,
        ),
        "max_request_body_size": body,
    }


def walk_proxy_slots(env: Mapping[str, str] | None = None) -> int:
    src = os.environ if env is None else env
    return _int(src, WEB_WALK_PROXY_MAX_VAR, DEFAULT_WALK_PROXY_MAX, low=1, high=MAX_SLOTS)


def walk_model_slots(env: Mapping[str, str] | None = None) -> int:
    src = os.environ if env is None else env
    return _int(src, WALK_MODEL_MAX_VAR, DEFAULT_WALK_MODEL_MAX, low=1, high=MAX_SLOTS)


class SlowGate:
    """Не больше `slots` одновременных медленных операций; лишним — отказ без ожидания."""

    def __init__(self, slots: int) -> None:
        self.slots = slots
        self._semaphore = threading.BoundedSemaphore(slots)

    def try_enter(self) -> bool:
        return self._semaphore.acquire(blocking=False)

    def leave(self) -> None:
        self._semaphore.release()


@functools.cache
def walk_model_gate() -> SlowGate:
    """Один предел на все вызовы модели сервиса обхода (подбор пункта и перевод)."""
    return SlowGate(walk_model_slots())
