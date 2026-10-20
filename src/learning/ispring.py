"""Клиент iSpring Learn API: подразделения и результаты прохождения курсов.

Только чтение. Схема доступа — `client_credentials`: токен живёт 30 минут и обновляется
сам, в том числе посреди долгого прохода (`TOKEN_MARGIN_SEC`). Запросы идут по одному,
с таймаутом; `429` и `5xx` повторяются с нарастающей паузой.

**Что здесь о людях.** Результаты приходят с идентификатором сотрудника (`userId`).
Клиент превращает их в `training_metrics.Result` и отдаёт вызывающему в память; ни в лог,
ни в текст ошибки идентификатор не попадает. Текст ошибки — путь без запроса и код
статуса, без тела ответа и без ключей.

Ответ — внешние данные: строка без нужных полей отбрасывается и считается, а не роняет
загрузку.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.domain.service_keys import ISPRING_HOST
from src.domain.training_metrics import Result

logger = logging.getLogger(__name__)

TIMEOUT_SEC = 30
PAGE_SIZE = 1000
MAX_PAGES = 200  # предохранитель от бесконечной пагинации
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
BACKOFF_BASE_SEC = 2.0
#: Токен обновляется заранее: запрос, начатый на последней секунде, не должен упасть на 401.
TOKEN_MARGIN_SEC = 120
DEFAULT_TOKEN_TTL_SEC = 1800
#: `userStatuses` в iSpring: 1 — активен, 3 — неактивен, 5 — уволен. Считаем только активных.
ACTIVE_USER_STATUS = "1"
#: Параметр обязан называться со скобками: `userStatuses=1` iSpring отвечает 500
#: (проверено вживую 20.10.2026), а `userStatuses[]=1` фильтрует.
USER_STATUS_PARAM = "userStatuses[]"

#: (метод, адрес, заголовки, тело) → (код, объект ответа). Подменяется в тестах.
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, Any]]


class IspringError(RuntimeError):
    """iSpring не ответил или ответил не тем. Сообщение — без ключей и без данных."""


@dataclass(frozen=True)
class Department:
    id: str
    name: str
    parent_id: str | None
    code: str | None


def urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None
) -> tuple[int, Any]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise IspringError(f"iSpring недоступен ({exc.__class__.__name__})") from exc


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_result(raw: Mapping[str, Any]) -> tuple[Result, str | None] | None:
    """Результат и название курса или `None`, если нет пользователя, курса или статуса."""
    user, course, status = (
        _text(raw.get("userId")),
        _text(raw.get("courseId")),
        _text(raw.get("completionStatus")),
    )
    if user is None or course is None or status is None:
        return None
    spent = raw.get("timeSpent")
    result = Result(
        user=user,
        course_id=course,
        status=status,
        is_overdue=raw.get("isOverdue") is True,
        time_spent=spent if isinstance(spent, int) and not isinstance(spent, bool) else None,
        score=_number(raw.get("awardedScore")),
        access_date=_when(raw.get("accessDate")),
        completion_date=_when(raw.get("completionDate")),
    )
    return result, _text(raw.get("courseTitle"))


class Client:
    """Сессия iSpring: токен, запросы, постраничное чтение."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        transport: Transport = urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        host: str = ISPRING_HOST,
    ) -> None:
        self._id = client_id
        self._secret = client_secret
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._host = host.rstrip("/")
        self._token: str | None = None
        self._expires_at = 0.0
        self.token_requests = 0

    def _authorize(self) -> str:
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self._id,
                "client_secret": self._secret,
            }
        ).encode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        status, data = self._send("POST", "/api/v3/token", headers, body)
        token = data.get("access_token") if isinstance(data, dict) else None
        if status != 200 or not isinstance(token, str) or not token:
            raise IspringError(f"iSpring не выдал токен (код {status})")
        ttl = data.get("expires_in")
        ttl = ttl if isinstance(ttl, (int, float)) and ttl > 0 else DEFAULT_TOKEN_TTL_SEC
        self.token_requests += 1
        self._token, self._expires_at = token, self._clock() + float(ttl)
        return token

    def _bearer(self) -> str:
        if self._token is None or self._clock() >= self._expires_at - TOKEN_MARGIN_SEC:
            return self._authorize()
        return self._token

    def _send(
        self, method: str, path: str, headers: Mapping[str, str], body: bytes | None
    ) -> tuple[int, Any]:
        """Один запрос с повторами `429`/`5xx`; прочие коды возвращаются как есть."""
        url = self._host + path
        label = path.split("?")[0]
        for attempt in range(MAX_ATTEMPTS):
            try:
                status, data = self._transport(method, url, headers, body)
            except IspringError:
                if attempt + 1 == MAX_ATTEMPTS:
                    raise
            else:
                if status not in RETRY_STATUSES:
                    return status, data
                if attempt + 1 == MAX_ATTEMPTS:
                    raise IspringError(f"iSpring ответил {status} на {label}")
            self._sleep(BACKOFF_BASE_SEC * 2**attempt)
        raise IspringError(f"iSpring не ответил на {label}")  # pragma: no cover

    def _get(self, path: str, params: Mapping[str, str]) -> Mapping[str, Any]:
        query = urllib.parse.urlencode(params)
        full = f"{path}?{query}" if query else path
        for fresh in (False, True):
            bearer = self._authorize() if fresh else self._bearer()
            headers = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
            status, data = self._send("GET", full, headers, None)
            if status == 401 and not fresh:
                continue  # токен отозван раньше срока — один раз берём новый
            if status != 200 or not isinstance(data, dict):
                raise IspringError(f"iSpring ответил {status} на {path}")
            return data
        raise IspringError(f"iSpring отказал в доступе на {path}")  # pragma: no cover

    def _pages(self, path: str, key: str, params: Mapping[str, str]) -> Iterator[Mapping[str, Any]]:
        token: str | None = None
        for _ in range(MAX_PAGES):
            page = {**params, "pageSize": str(PAGE_SIZE), **({"pageToken": token} if token else {})}
            data = self._get(path, page)
            items = data.get(key)
            if not isinstance(items, list):
                raise IspringError(f"В ответе {path} нет списка {key}")
            yield from (item for item in items if isinstance(item, dict))
            token = _text(data.get("nextPageToken"))
            if token is None:
                return
        raise IspringError(f"{path}: больше {MAX_PAGES} страниц — остановлено")

    def departments(self) -> list[Department]:
        """Все подразделения; строка без идентификатора или названия отбрасывается."""
        found = []
        for raw in self._pages("/departments", "departments", {}):
            ident, name = _text(raw.get("departmentId")), _text(raw.get("name"))
            if ident and name:
                found.append(
                    Department(
                        ident, name, _text(raw.get("parentDepartmentId")), _text(raw.get("code"))
                    )
                )
        return found

    def results(self, department_id: str) -> tuple[list[Result], dict[str, str], int]:
        """Результаты активных сотрудников подразделения (без вложенных) в память.

        Возвращает результаты, названия курсов по коду и число отброшенных строк.
        """
        rows: list[Result] = []
        titles: dict[str, str] = {}
        dropped = 0
        params = {"departmentIds": department_id, USER_STATUS_PARAM: ACTIVE_USER_STATUS}
        for raw in self._pages("/learners/results", "results", params):
            parsed = parse_result(raw)
            if parsed is None:
                dropped += 1
                continue
            result, title = parsed
            rows.append(result)
            if title:
                titles[result.course_id] = title
        return rows, titles, dropped
