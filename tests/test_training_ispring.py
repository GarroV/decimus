"""Клиент iSpring (#906): токен, повторы, пагинация, отказы без секретов и без данных людей."""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import Any

import pytest

from src.learning import ispring
from src.learning.ispring import Client, IspringError

SECRET = "super-secret-value-123"
CLIENT_ID = "client-id-456"


class Fake:
    """Транспорт iSpring: очередь ответов по порядку и журнал запросов."""

    def __init__(self, *responses: tuple[int, Any]) -> None:
        self.queue = list(responses)
        self.calls: list[tuple[str, str, Mapping[str, str], bytes | None]] = []

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None):
        self.calls.append((method, url, headers, body))
        return self.queue.pop(0)

    def paths(self) -> list[str]:
        return [urllib.parse.urlsplit(c[1]).path for c in self.calls]


def _token(ttl: int = 1800, value: str = "tok") -> tuple[int, Any]:
    return 200, {"access_token": value, "expires_in": ttl}


def _result(user: str = "u1", course: str = "c1", status: str = "complete", **extra: Any) -> dict:
    return {"userId": user, "courseId": course, "courseTitle": "Курс", "completionStatus": status,
            "isOverdue": False, **extra}  # fmt: skip


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _client(fake: Fake, clock: Clock | None = None, sleeps: list[float] | None = None) -> Client:
    clock = clock or Clock()
    log = sleeps if sleeps is not None else []
    return Client(CLIENT_ID, SECRET, transport=fake, sleep=log.append, clock=clock)


def test_токен_берётся_формой_client_credentials() -> None:
    fake = Fake(_token(), (200, {"departments": []}))
    _client(fake).departments()
    method, url, _h, body = fake.calls[0]
    assert (method, url.endswith("/api/v3/token")) == ("POST", True)
    form = dict(urllib.parse.parse_qsl((body or b"").decode()))
    assert form["grant_type"] == "client_credentials"
    assert form["client_id"] == CLIENT_ID


def test_запрос_идёт_с_bearer_и_просит_json() -> None:
    fake = Fake(_token(value="abc"), (200, {"departments": []}))
    _client(fake).departments()
    headers = fake.calls[1][2]
    assert headers["Authorization"] == "Bearer abc"
    assert headers["Accept"] == "application/json"


def test_пагинация_идёт_по_токену_страницы() -> None:
    fake = Fake(
        _token(),
        (200, {"results": [_result("u1")], "nextPageToken": "p2"}),
        (200, {"results": [_result("u2")]}),
    )
    rows, titles, dropped = _client(fake).results("dept-1")
    assert [r.user for r in rows] == ["u1", "u2"]
    assert (titles, dropped) == ({"c1": "Курс"}, 0)
    assert "pageToken=p2" in fake.calls[2][1]
    assert "pageToken" not in fake.calls[1][1]


def test_результаты_берутся_по_подразделению_и_только_активных() -> None:
    fake = Fake(_token(), (200, {"results": []}))
    _client(fake).results("dept-1")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.calls[1][1]).query)
    assert query["departmentIds"] == ["dept-1"]
    # iSpring отвечает 500 на `userStatuses=1` и фильтрует только `userStatuses[]=1`.
    assert query["userStatuses[]"] == ["1"]
    assert "userStatuses" not in query


def test_токен_обновляется_до_истечения_посреди_прохода() -> None:
    clock = Clock()
    fake = Fake(
        _token(ttl=1800, value="first"),
        (200, {"results": [], "nextPageToken": "p2"}),
        _token(ttl=1800, value="second"),
        (200, {"results": []}),
    )

    def transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None):
        answer = fake(method, url, headers, body)
        if len(fake.calls) == 2:  # первая страница получена; до второй прошло 29 минут
            clock.now += 1740
        return answer

    client = Client(CLIENT_ID, SECRET, transport=transport, sleep=lambda _s: None, clock=clock)
    client.results("dept-1")
    assert client.token_requests == 2
    assert fake.calls[-1][2]["Authorization"] == "Bearer second"


def test_401_один_раз_берёт_новый_токен() -> None:
    fake = Fake(_token(value="old"), (401, None), _token(value="new"), (200, {"departments": []}))
    _client(fake).departments()
    assert fake.calls[-1][2]["Authorization"] == "Bearer new"


def test_429_и_5xx_повторяются_с_нарастающей_паузой() -> None:
    sleeps: list[float] = []
    fake = Fake(_token(), (429, None), (503, None), (200, {"departments": []}))
    _client(fake, sleeps=sleeps).departments()
    assert sleeps == [ispring.BACKOFF_BASE_SEC, ispring.BACKOFF_BASE_SEC * 2]


def test_повторы_кончаются_отказом_без_секрета_и_запроса() -> None:
    fake = Fake(_token(), *[(500, None)] * ispring.MAX_ATTEMPTS)
    with pytest.raises(IspringError) as raised:
        _client(fake).results("dept-secret-id")
    text = str(raised.value)
    assert "500" in text and "/learners/results" in text
    assert SECRET not in text and CLIENT_ID not in text
    assert "dept-secret-id" not in text  # в тексте только путь без запроса


def test_нет_токена_отказ_без_секрета() -> None:
    fake = Fake((400, {"error": "invalid_client"}))
    with pytest.raises(IspringError) as raised:
        _client(fake).departments()
    assert SECRET not in str(raised.value)


def test_строка_без_пользователя_курса_или_статуса_отбрасывается_и_считается() -> None:
    fake = Fake(
        _token(),
        (200, {"results": [_result(), {"courseId": "c"}, {"userId": "u", "courseId": "c"}]}),
    )
    rows, _titles, dropped = _client(fake).results("d")
    assert (len(rows), dropped) == (1, 2)


def test_поля_результата_разбираются() -> None:
    fake = Fake(
        _token(),
        (
            200,
            {
                "results": [
                    _result(
                        status="passed",
                        timeSpent=125,
                        awardedScore=80.5,
                        isOverdue=True,
                        accessDate="2026-10-01T10:00:00+03:00",
                        completionDate="2026-10-02T10:00:00+03:00",
                    )
                ]
            },
        ),
    )
    row = _client(fake).results("d")[0][0]
    assert (row.time_spent, row.score, row.is_overdue) == (125, 80.5, True)
    assert row.completion_date and row.access_date
    assert (row.completion_date - row.access_date).days == 1


def test_нет_списка_в_ответе_отказ() -> None:
    fake = Fake(_token(), (200, {"oops": []}))
    with pytest.raises(IspringError):
        _client(fake).departments()
