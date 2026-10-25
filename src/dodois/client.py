"""Разговор с Dodo IS: вход устройства, продление, имя учётки, счёт открытых пиццерий (D640).

**Только чтение данных.** К `api.dodois.com` идут одни GET; POST — только на сервер
авторизации (`auth.dodois.com`: вход устройства, обмен кода, продление). Данных людей не
берём: из `userinfo` — имя и почта учётки, подтвердившей вход, больше ничего.

**Значения не светятся.** Ключи приложения и входа уходят в тело или заголовок запроса;
ни в исключения (`DodoisError` несёт только вид отказа), ни в журнал они не попадают.
Перенаправления не выполняются: учётные данные не должны уйти на другой адрес.

Одна точка выхода в сеть — `_open`: тесты подменяют её, настоящих запросов не делают.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from src.domain import dodois as rules

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 20
#: Сколько ждём по `Retry-After` до одного повтора запроса; больше — отказ «лимит».
MAX_RETRY_WAIT_SEC = 30
RESPONSE_LIMIT_BYTES = 4 * 1024 * 1024

NETWORK = "network"
RATE_LIMITED = "rate_limited"
UNAUTHORIZED = "unauthorized"


class DodoisError(Exception):
    """Не вышло поговорить с Dodo IS. `kind` — вид отказа (он же причина в базе)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class RefreshRejected(DodoisError):
    """Dodo IS отказал в продлении: ключ продления больше не принимается — вход истёк."""

    def __init__(self) -> None:
        super().__init__("refresh_rejected")


@dataclass(frozen=True)
class Credentials:
    """Пара ключей приложения. Не печатается."""

    client_id: str
    client_secret: str

    def __repr__(self) -> str:
        return "Credentials(<скрыто>)"


@dataclass(frozen=True)
class DeviceStart:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int

    def __repr__(self) -> str:  # код устройства не светится
        return "DeviceStart(<скрыто>)"


@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str
    expires_in: int
    scope: str | None

    def __repr__(self) -> str:
        return "TokenPair(<скрыто>)"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _open(request: urllib.request.Request) -> Response:
    """Единственный выход в сеть. Ответ любого кода — ответ; сеть упала — `DodoisError`."""
    try:
        with _opener.open(request, timeout=TIMEOUT_SEC) as raw:
            status, headers, data = raw.status, dict(raw.headers), raw.read(RESPONSE_LIMIT_BYTES)
    except urllib.error.HTTPError as exc:
        status, headers = exc.code, dict(exc.headers or {})
        try:
            data = exc.read(RESPONSE_LIMIT_BYTES)
        except OSError:
            data = b""
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DodoisError(NETWORK) from None
    try:
        body = json.loads(data) if data else None
    except ValueError:
        body = None
    return Response(status, {k.lower(): v for k, v in headers.items()}, body)


def _hosts(contour: str) -> rules.ContourHosts:
    found = rules.HOSTS.get(contour)
    if found is None:
        raise DodoisError(UNAUTHORIZED)
    return found


def _post_form(url: str, fields: dict[str, str]) -> Response:
    request = urllib.request.Request(  # noqa: S310
        url,
        data=urllib.parse.urlencode(fields).encode(),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return _open(request)


def _get(url: str, token: str | None = None) -> Response:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _open(urllib.request.Request(url, headers=headers))  # noqa: S310


def _error_code(response: Response) -> str:
    body = response.body
    return str(body.get("error", "")) if isinstance(body, dict) else ""


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _pair(response: Response) -> TokenPair:
    body = response.body
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("access_token"), str)
        or not isinstance(body.get("refresh_token"), str)
        or not body["access_token"]
        or not body["refresh_token"]
    ):
        raise DodoisError(NETWORK)
    scope = body.get("scope")
    return TokenPair(
        access=body["access_token"],
        refresh=body["refresh_token"],
        expires_in=_int(body.get("expires_in"), 86400),
        scope=scope if isinstance(scope, str) and scope else None,
    )


def _failure(response: Response) -> DodoisError:
    if response.status == 429:
        return DodoisError(RATE_LIMITED)
    if response.status in (400, 401, 403):
        return DodoisError(UNAUTHORIZED)
    return DodoisError(NETWORK)


# --- вход устройства и продление ------------------------------------------------------


def start_device(credentials: Credentials, contour: str) -> DeviceStart:
    """`POST /connect/deviceauthorization`: код для человека и ссылка подтверждения."""
    response = _post_form(
        _hosts(contour).auth + "/connect/deviceauthorization",
        {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scope": rules.SCOPES,
        },
    )
    body = response.body
    if response.status != 200 or not isinstance(body, dict):
        raise _failure(response)
    link = body.get("verification_uri_complete") or body.get("verification_uri")
    if not (
        isinstance(body.get("device_code"), str)
        and isinstance(body.get("user_code"), str)
        and isinstance(link, str)
    ):
        raise DodoisError(NETWORK)
    return DeviceStart(
        device_code=body["device_code"],
        user_code=body["user_code"],
        verification_uri=link,
        expires_in=_int(body.get("expires_in"), 300),
        interval=max(1, _int(body.get("interval"), 5)),
    )


PENDING = "pending"
SLOW_DOWN = "slow_down"
EXPIRED = "expired"
DENIED = "denied"


def poll_device(credentials: Credentials, contour: str, device_code: str) -> TokenPair | str:
    """Один опрос `POST /connect/token`: пара ключей либо `pending` / `slow_down` / ..."""
    response = _post_form(
        _hosts(contour).auth + "/connect/token",
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        },
    )
    if response.status == 200:
        return _pair(response)
    answer = {
        "authorization_pending": PENDING,
        "slow_down": SLOW_DOWN,
        "expired_token": EXPIRED,
        "access_denied": DENIED,
    }.get(_error_code(response))
    if answer is not None:
        return answer
    raise _failure(response)


def refresh_tokens(credentials: Credentials, contour: str, refresh_token: str) -> TokenPair:
    """`grant_type=refresh_token`. Ключ продления одноразовый: ответ несёт новую пару."""
    response = _post_form(
        _hosts(contour).auth + "/connect/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
        },
    )
    if response.status == 200:
        return _pair(response)
    if _error_code(response) == "invalid_grant":
        raise RefreshRejected
    raise _failure(response)


def userinfo(contour: str, access_token: str) -> tuple[str | None, str | None]:
    """Имя и почта учётки Dodo IS, подтвердившей вход; любой сбой — пустые."""
    try:
        response = _get(_hosts(contour).auth + rules.USERINFO_PATH, access_token)
    except DodoisError:
        return None, None
    body = response.body
    if response.status != 200 or not isinstance(body, dict):
        return None, None

    def text(key: str) -> str | None:
        value = body.get(key)
        return value.strip()[:200] or None if isinstance(value, str) else None

    return text("name"), text("email")


# --- сколько пиццерий открыто ---------------------------------------------------------

PIZZERIA_TYPE = 1
WORKING_STATE = 1


def working_pizzerias(country: str) -> list[str]:
    """UUID работающих пиццерий страны — публичный список, без ключа."""
    response = _get(rules.UNITINFO_URL.format(cc=country.lower()))
    if response.status == 429:
        raise DodoisError(RATE_LIMITED)
    if response.status != 200 or not isinstance(response.body, list):
        raise DodoisError(NETWORK)
    found: list[str] = []
    for unit in response.body:
        if (
            isinstance(unit, dict)
            and unit.get("Type") == PIZZERIA_TYPE
            and unit.get("State") == WORKING_STATE
            and isinstance(unit.get("UUId"), str)
        ):
            found.append(unit["UUId"])
    return found


def _wait_seconds(response: Response) -> int:
    try:
        return max(1, int(float(response.headers.get("retry-after", "1"))))
    except ValueError:
        return 1


def _stop_sales(
    country: str,
    contour: str,
    access_token: str,
    units: Sequence[str],
    today: date,
    sleep: Callable[[float], None],
) -> Response:
    query = urllib.parse.urlencode(
        {
            "units": ",".join(units),
            "from": f"{today.isoformat()}T00:00:00",
            "to": f"{(today + timedelta(days=1)).isoformat()}T00:00:00",
        },
        safe=",:",
    )
    url = _hosts(contour).api + rules.STOPSALES_PATH.format(cc=country.lower()) + "?" + query
    response = _get(url, access_token)
    if response.status == 429:
        wait = _wait_seconds(response)
        if wait > MAX_RETRY_WAIT_SEC:
            raise DodoisError(RATE_LIMITED)
        sleep(wait)
        response = _get(url, access_token)
    return response


def count_open(
    country: str,
    contour: str,
    access_token: str,
    units: Sequence[str],
    today: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Сколько из `units` открыто для этого входа: ответ 200 — открыто, `NoAccessToUnit` — нет.

    Пачка до `UNITS_PER_CALL`; отказ по доступу делит пачку пополам, пока не найдёт, на
    какой пиццерии он. Все запросы — GET.
    """
    opened = 0
    queue = [list(units[i : i + rules.UNITS_PER_CALL]) for i in range(0, len(units), 30)]
    while queue:
        batch = queue.pop()
        response = _stop_sales(country, contour, access_token, batch, today, sleep)
        if response.status == 200:
            opened += len(batch)
        elif response.status == 403 and _no_access(response):
            if len(batch) > 1:
                middle = len(batch) // 2
                queue.extend((batch[:middle], batch[middle:]))
        elif response.status == 401:
            raise DodoisError(UNAUTHORIZED)
        else:
            raise _failure(response)
    return opened


def _no_access(response: Response) -> bool:
    body = response.body
    return isinstance(body, dict) and body.get("code") == "NoAccessToUnit"
