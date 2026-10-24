"""Проверка ключа у провайдера до записи (D576): один дешёвый вызов с введённым значением.

`KeyRejected` — провайдер значение не принял (401/403, неверная пара); `KeyUnverified` —
проверить не удалось (сеть, лимит, сбой провайдера, таймаут). В обоих отказах нет ни
значения, ни текста ответа провайдера: только код HTTP-статуса, чтобы админ видел причину.
Таймаут — `TIMEOUT_SEC`; перенаправления не выполняются: учётные данные не должны уйти на
другой адрес.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from src.domain.service_keys import ISPRING_HOST
from src.ratings import pointer
from src.recognize import client
from src.recognize.errors import ModelKeyRejected, ModelUnavailable

TIMEOUT_SEC = 15
ISPRING_TOKEN_PATH = "/api/v3/token"  # noqa: S105 — путь запроса, не секрет
POINTER_PROBE_PATH = "/networks?limit=1&offset=0"
#: Коды ответа, по которым провайдер считает значение неверным.
REJECTED_STATUSES = frozenset({400, 401, 403})
#: Pointer отвечает на превышение лимита кодом 400 с телом «слишком много запросов»
#: (#1256): это не отказ в ключе. Тело читается только ради этих слов и никуда не идёт.
RATE_LIMIT_MARKERS = ("слишком много запросов", "too many requests")
RATE_LIMIT_BODY_BYTES = 2048


class KeyRejected(Exception):
    """Провайдер значение не принял. `status` — HTTP-код, если он был."""

    def __init__(self, status: int | None = None) -> None:
        super().__init__("rejected")
        self.status = status


class KeyUnverified(Exception):
    """Проверить не удалось. `status` — HTTP-код, если он был."""

    def __init__(self, status: int | None = None) -> None:
        super().__init__("unverified")
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _rate_limited(exc: urllib.error.HTTPError) -> bool:
    try:
        body = exc.read(RATE_LIMIT_BODY_BYTES) if exc.fp is not None else b""
    except OSError:
        return False
    text = body.decode("utf-8", "replace").lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def _call(request: urllib.request.Request) -> Any:
    try:
        with _opener.open(request, timeout=TIMEOUT_SEC) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in REJECTED_STATUSES and not _rate_limited(exc):
            raise KeyRejected(exc.code) from None
        raise KeyUnverified(exc.code) from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise KeyUnverified(None) from None


def probe_ispring(values: Mapping[str, str]) -> None:
    """`POST /api/v3/token` с `grant_type=client_credentials`; токен не сохраняется."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": values["client_id"],
            "client_secret": values["client_secret"],
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310
        ISPRING_HOST + ISPRING_TOKEN_PATH,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    answer = _call(request)
    if not isinstance(answer, dict) or not answer.get("access_token"):
        raise KeyUnverified(None)


def probe_pointer(values: Mapping[str, str]) -> None:
    """Самый дешёвый вызов с ключом: одна сеть из списка `/networks`."""
    request = urllib.request.Request(  # noqa: S310
        pointer.BASE_URL + POINTER_PROBE_PATH,
        headers={"Authorization": f"Bearer {values['api_key']}"},
    )
    if not isinstance(_call(request), dict):
        raise KeyUnverified(None)


def probe_openai(values: Mapping[str, str]) -> None:
    """Тот же вызов, что и раньше (D491): список моделей."""
    try:
        client.verify_key(values["api_key"])
    except ModelKeyRejected:
        raise KeyRejected(None) from None
    except ModelUnavailable:
        raise KeyUnverified(None) from None


PROBES: Mapping[str, Callable[[Mapping[str, str]], None]] = {
    "openai": probe_openai,
    "pointer": probe_pointer,
    "ispring": probe_ispring,
}
