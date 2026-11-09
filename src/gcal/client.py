"""Разговор с Google Календарём: продление доступа, события, отзыв ключа.

Только сеть и разбор ответов, без базы и без решений «что ставить» — их принимает
`src/gcal/sync.py`. Любая осечка — `CalendarError` с КОДОМ причины (`invalid_grant`,
`SERVICE_DISABLED`, `http_403`…): код попадает в журнал и в строку «календарь не ответил»
на экране, а текст ответа Google — нет (в нём бывает почта человека).

Скоуп один — `calendar.events.owned` (выбор и причина — `docs/39-calendar-deadline.md`).
Календарь всегда `primary`: событие появляется в основном календаре проверяющего.

`opener` — точка подмены для проверки: сам разговор тривиален, а разбор отказов решает,
увидит ли человек внятную причину.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

#: Право на события в календарях, которыми человек владеет: создать, изменить, удалить.
#: Основной календарь — его собственный. Чужие календари (общие, на которые подписан) не
#: затрагиваются; `calendar.events` дал бы и их, `calendar.app.created` — только вторичный
#: календарь, созданный приложением, а не основной.
EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 — адрес, не секрет
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
EVENTS_ENDPOINT = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
NETWORK_TIMEOUT_SECONDS = 10

#: За сколько минут до начала дня сработает уведомление. API принимает 0–40320: «утром того
#: же дня» у события на весь день он выразить не умеет (отсчёт — от полуночи дня события), поэтому
#: 0 — уведомление в начале дня события.
REMINDER_MINUTES_BEFORE_START = 0

GOOGLE_CLIENT_ID_VAR = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_VAR = "GOOGLE_CLIENT_SECRET"  # noqa: S105 — ИМЯ переменной

#: Коды, после которых повтор бессмыслен, пока человек не переподключится.
DEAD_GRANT_CODES = frozenset({"invalid_grant", "invalid_client", "unauthorized_client"})
#: Коды, когда события уже нет в календаре (человек удалил сам): причина из тела ответа или
#: код ответа, если тела нет.
GONE_CODES = frozenset({"notFound", "deleted", "http_404", "http_410"})

Opener = Callable[..., Any]


class CalendarError(Exception):
    """Календарь не ответил. `code` — машинная причина без данных человека."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ClientKeys:
    client_id: str
    client_secret: str


def keys_from_env(env: dict[str, str] | None = None) -> ClientKeys | None:
    """Клиент Google из окружения (те же переменные, что у входа); нет — `None`."""
    src = os.environ if env is None else env
    client_id = (src.get(GOOGLE_CLIENT_ID_VAR) or "").strip()
    secret = (src.get(GOOGLE_CLIENT_SECRET_VAR) or "").strip()
    return ClientKeys(client_id, secret) if client_id and secret else None


def reason_code(сбой: BaseException) -> str:
    """Код причины из тела ошибки Google; нет тела — `http_<код>` или имя типа."""
    http = getattr(сбой, "code", None)
    читать = getattr(сбой, "read", None)
    коды: list[str] = []
    if читать is not None:
        try:
            тело = json.loads(читать() or b"{}")
        except Exception:  # разбор причины не должен ронять обработку сбоя
            тело = {}
        ошибка = тело.get("error") if isinstance(тело, dict) else None
        if isinstance(ошибка, str):
            коды.append(ошибка)
        elif isinstance(ошибка, dict):
            for пункт in ошибка.get("errors") or []:
                if isinstance(пункт, dict) and isinstance(пункт.get("reason"), str):
                    коды.append(пункт["reason"])
            for деталь in ошибка.get("details") or []:
                if isinstance(деталь, dict) and isinstance(деталь.get("reason"), str):
                    коды.append(деталь["reason"])
    for код in коды:
        if код.replace("_", "").isalnum() and len(код) <= 64:
            return код
    if isinstance(http, int):
        return f"http_{http}"
    return type(сбой).__name__.lower()[:64]


def _call(opener: Opener, запрос: urllib.request.Request) -> dict[str, Any]:
    try:
        with opener(запрос, timeout=NETWORK_TIMEOUT_SECONDS) as ответ:
            сырое = ответ.read()
    except Exception as сбой:
        raise CalendarError(reason_code(сбой)) from сбой
    if not сырое:
        return {}
    try:
        тело = json.loads(сырое)
    except ValueError as сбой:
        raise CalendarError("bad_json") from сбой
    return тело if isinstance(тело, dict) else {}


def access_token(
    keys: ClientKeys, refresh_token: str, *, opener: Opener = urllib.request.urlopen
) -> str:
    """Короткий ключ доступа по ключу продления."""
    запрос = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=urllib.parse.urlencode(
            {
                "client_id": keys.client_id,
                "client_secret": keys.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    токен = _call(opener, запрос).get("access_token")
    if not isinstance(токен, str) or not токен:
        raise CalendarError("no_access_token")
    return токен


def revoke(token: str, *, opener: Opener = urllib.request.urlopen) -> None:
    """Отозвать ключ у Google. Ключ уже мёртв (`invalid_token`) — это тоже «отозван»."""
    запрос = urllib.request.Request(
        REVOKE_ENDPOINT,
        data=urllib.parse.urlencode({"token": token}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        _call(opener, запрос)
    except CalendarError as сбой:
        if сбой.code != "invalid_token":
            raise


def event_body(*, title: str, description: str, due: date) -> dict[str, Any]:
    """Событие на весь день в дату срока: без гостей, с уведомлением календаря (не письмом)."""
    return {
        "summary": title,
        "description": description,
        "start": {"date": due.isoformat()},
        # Конец события на весь день — следующий день, не включительно (правило Google).
        "end": {"date": (due + timedelta(days=1)).isoformat()},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": REMINDER_MINUTES_BEFORE_START}],
        },
    }


def _event_request(
    token: str, method: str, body: dict[str, Any] | None, event_id: str | None = None
) -> urllib.request.Request:
    адрес = EVENTS_ENDPOINT
    if event_id is not None:
        адрес += "/" + urllib.parse.quote(event_id, safe="")
    # Письма никому не уходят ни при каком исходе: гостей нет, и сам запрос это говорит.
    адрес += "?" + urllib.parse.urlencode({"sendUpdates": "none"})
    return urllib.request.Request(  # noqa: S310
        адрес,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )


def create_event(
    token: str, body: dict[str, Any], *, opener: Opener = urllib.request.urlopen
) -> str:
    """Создать событие, вернуть его номер. Ответ без номера — сбой, а не успех."""
    номер = _call(opener, _event_request(token, "POST", body)).get("id")
    if not isinstance(номер, str) or not номер:
        raise CalendarError("no_event_id")
    return номер


def update_event(
    token: str, event_id: str, body: dict[str, Any], *, opener: Opener = urllib.request.urlopen
) -> None:
    """Перезаписать поля события (PATCH). Нет события (`GONE_CODES`) — решает вызывающий."""
    _call(opener, _event_request(token, "PATCH", body, event_id))


def delete_event(token: str, event_id: str, *, opener: Opener = urllib.request.urlopen) -> None:
    """Удалить событие; уже нет (404, 410) — цель достигнута."""
    try:
        _call(opener, _event_request(token, "DELETE", None, event_id))
    except CalendarError as сбой:
        if сбой.code not in GONE_CODES:
            raise
