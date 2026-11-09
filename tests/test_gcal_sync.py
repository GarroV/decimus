"""Сводка событий срока отчёта с календарём (D740, #1590): создать, сдвинуть, снять, не сломать.

Сети и базы нет: Google — двойник `opener`, база — двойник, который держит то, что держит
`calendar_store` (проверки окна, стоящие события, пометки сбоя). Проверяется то, что делаем
МЫ: что уходит в Google и что запоминаем. Главное правило — сбой календаря никого не ломает.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from datetime import date
from typing import Any

import pytest

from src.db import calendar_store, secret_crypto
from src.gcal import client, sync

СЕГОДНЯ = date(2026, 11, 9)
КЛЮЧИ = client.ClientKeys("клиент", "секрет")
ЛЮДИ = "u-1"


class Ответ:
    def __init__(self, тело: dict[str, Any] | None = None) -> None:
        self._тело = json.dumps(тело or {}).encode()

    def __enter__(self) -> Ответ:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._тело


def _http(код: int, тело: dict[str, Any] | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://x",
        код,
        "x",
        None,
        io.BytesIO(json.dumps(тело or {}).encode()),  # type: ignore[arg-type]
    )


class Google:
    """Двойник Google: разбирает запрос по методу и адресу, ведёт «календарь» и журнал вызовов."""

    def __init__(self) -> None:
        self.календарь: dict[str, dict[str, Any]] = {}
        self.вызовы: list[tuple[str, str]] = []
        self.сбой_токена: urllib.error.HTTPError | None = None
        self.сбой_событий: urllib.error.HTTPError | None = None
        self.следующий = 1

    def __call__(self, запрос: Any, timeout: float) -> Ответ:
        адрес = urllib.parse.urlsplit(запрос.full_url)
        метод = запрос.get_method()
        self.вызовы.append((метод, адрес.path))
        if адрес.path == "/token":
            if self.сбой_токена:
                raise self.сбой_токена
            return Ответ({"access_token": "короткий"})
        assert urllib.parse.parse_qs(адрес.query) == {"sendUpdates": ["none"]}
        if self.сбой_событий:
            raise self.сбой_событий
        тело = json.loads(запрос.data) if запрос.data else {}
        номер = адрес.path.rsplit("/", 1)[-1]
        if метод == "POST":
            новый = f"ev{self.следующий}"
            self.следующий += 1
            self.календарь[новый] = тело
            return Ответ({"id": новый})
        if номер not in self.календарь:
            raise _http(404, {"error": {"errors": [{"reason": "notFound"}]}})
        if метод == "PATCH":
            self.календарь[номер] |= тело
        else:
            del self.календарь[номер]
        return Ответ()


class База:
    """Двойник `calendar_store`: проверки, стоящие события и пометки сбоя."""

    def __init__(self) -> None:
        self.проверки: dict[str, dict[str, Any]] = {}
        self.события: dict[str, calendar_store.Orphan] = {}
        self.стоит: dict[str, tuple[str, date, str]] = {}
        self.проблемы: dict[str, str] = {}
        self.журнал: list[tuple[str, str]] = []
        self.нет_ключа = False

    def добавить(self, ид: str, день: date, *, unit: str = "Белград-1", lang: str = "ru") -> None:
        self.проверки[ид] = {"day": день, "unit": unit, "lang": lang}

    def снять(self, ид: str) -> None:
        """Проверка отклонена: роль приложения её больше не видит."""
        self.проверки.pop(ид)

    # --- то, что зовёт sync ---
    def candidates(self, *, since: date, dead: tuple[str, ...]) -> list[calendar_store.Candidate]:
        if self.проблемы.get(ЛЮДИ) in dead:
            return []
        результат = []
        for ид, п in self.проверки.items():
            ev = self.стоит.get(ид)
            результат.append(
                calendar_store.Candidate(
                    ид, ЛЮДИ, п["unit"], п["day"], п["lang"], *(ev if ev else (None, None, None))
                )
            )
        return результат

    def orphans(self) -> list[calendar_store.Orphan]:
        return [
            calendar_store.Orphan(ид, ЛЮДИ, ev[0])
            for ид, ev in self.стоит.items()
            if ид not in self.проверки
        ]

    def remember_event(
        self, ид: str, user_id: str, *, event_id: str, due: date, title: str
    ) -> None:
        self.стоит[ид] = (event_id, due, title)

    def forget_event(self, ид: str) -> None:
        self.стоит.pop(ид, None)

    def mark_problem(self, user_id: str, code: str) -> None:
        self.проблемы[user_id] = code

    def clear_problem(self, user_id: str) -> None:
        self.проблемы.pop(user_id, None)

    def journal_problem(self, user_id: str, code: str, *, inspection_id: str | None = None) -> None:
        self.журнал.append((code, inspection_id or ""))

    def refresh_token_of(self, user_id: str) -> str | None:
        if self.нет_ключа:
            raise secret_crypto.SecretCryptoError("двойник: ключ не открылся")
        return "долгий"


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> База:
    двойник = База()
    for имя in (
        "candidates",
        "orphans",
        "remember_event",
        "forget_event",
        "mark_problem",
        "clear_problem",
        "journal_problem",
        "refresh_token_of",
    ):
        monkeypatch.setattr(calendar_store, имя, getattr(двойник, имя))
    monkeypatch.setattr(client, "TOKEN_ENDPOINT", "https://oauth.test/token")
    return двойник


@pytest.fixture
def google() -> Google:
    return Google()


def _проход(google: Google, **ещё: Any) -> sync.PassResult:
    return sync.run_pass(
        today=СЕГОДНЯ, keys=КЛЮЧИ, opener=google, link_for=lambda ид: f"https://d.test/{ид}", **ещё
    )


def test_завершённая_проверка_получает_событие_на_третий_рабочий_день(
    база: База, google: Google
) -> None:
    база.добавить("i1", date(2026, 11, 6))  # пятница

    итог = _проход(google)

    assert итог.created == 1
    событие = next(iter(google.календарь.values()))
    assert событие["start"] == {"date": "2026-11-11"}, "пятница → среда"
    assert событие["summary"] == "Отправить отчёт по проверке — Белград-1 (06.11)"
    assert событие["description"] == "Проверка в Decimus: https://d.test/i1"
    assert "attendees" not in событие
    assert база.стоит["i1"] == ("ev1", date(2026, 11, 11), событие["summary"])


def test_название_на_английском_для_английского_интерфейса(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6), lang="en")

    _проход(google)

    событие = next(iter(google.календарь.values()))
    assert событие["summary"].startswith("Send the inspection report — ")
    assert событие["description"].startswith("Inspection in Decimus: ")


def test_второй_проход_ничего_не_делает(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)
    google.вызовы.clear()

    итог = _проход(google)

    assert (итог.created, итог.updated, итог.deleted) == (0, 0, 0)
    assert google.вызовы == []


def test_перенос_даты_сдвигает_то_же_событие(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)

    база.добавить("i1", date(2026, 11, 4))  # `move_inspection`: среда → срок в понедельник
    итог = _проход(google)

    assert итог.updated == 1 and len(google.календарь) == 1
    assert google.календарь["ev1"]["start"] == {"date": "2026-11-09"}
    assert база.стоит["i1"][0] == "ev1", "номер события не меняется"


def test_перенос_пиццерии_переименовывает_событие(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)

    база.добавить("i1", date(2026, 11, 6), unit="Нови-Сад")
    _проход(google)

    assert google.календарь["ev1"]["summary"] == "Отправить отчёт по проверке — Нови-Сад (06.11)"


def test_отклонённая_проверка_снимает_событие(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)

    база.снять("i1")
    итог = _проход(google)

    assert итог.deleted == 1 and google.календарь == {}
    assert "i1" not in база.стоит


def test_событие_удалённое_человеком_пересоздаётся_при_переносе(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)
    google.календарь.clear()

    база.добавить("i1", date(2026, 11, 5))
    _проход(google)

    assert list(google.календарь) == ["ev2"] and база.стоит["i1"][0] == "ev2"


def test_старая_проверка_нового_события_не_получает(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 10, 20))  # срок 23.10 прошёл давно

    итог = _проход(google)

    assert итог.created == 0 and google.вызовы == []


def test_сбой_google_не_поднимается_и_виден_в_журнале_и_на_подключении(
    база: База, google: Google
) -> None:
    база.добавить("i1", date(2026, 11, 6))
    google.сбой_событий = _http(500)

    итог = _проход(google)  # не бросает

    assert итог.failed == 1 and итог.created == 0
    assert база.журнал == [("http_500", "i1")]
    assert база.проблемы == {ЛЮДИ: "http_500"}, "человеку на экране видно «переподключите»"
    assert "i1" not in база.стоит


def test_временный_сбой_повторяется_и_пометка_снимается(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    google.сбой_событий = _http(503)
    _проход(google)

    google.сбой_событий = None
    итог = _проход(google)

    assert итог.created == 1 and база.проблемы == {}


def test_мёртвый_ключ_продления_помечает_и_ждёт_переподключения(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    google.сбой_токена = _http(400, {"error": "invalid_grant"})

    _проход(google)

    assert база.проблемы == {ЛЮДИ: "invalid_grant"}
    google.вызовы.clear()
    _проход(google)
    assert google.вызовы == [], "мёртвое подключение пропускается до переподключения"


def test_ключ_который_не_открылся_помечается_и_не_роняет_проход(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    база.нет_ключа = True

    _проход(google)

    assert база.проблемы == {ЛЮДИ: sync.UNREADABLE}
    assert google.вызовы == []


def test_без_клиента_google_проход_пропускается(
    база: База, google: Google, monkeypatch: pytest.MonkeyPatch
) -> None:
    база.добавить("i1", date(2026, 11, 6))
    monkeypatch.delenv(client.GOOGLE_CLIENT_ID_VAR, raising=False)

    итог = sync.run_pass(today=СЕГОДНЯ, opener=google)

    assert итог == sync.PassResult() and google.вызовы == []


def test_временный_сбой_токена_не_стирает_запись_об_осиротевшем_событии(
    база: База, google: Google
) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)
    база.снять("i1")
    google.сбой_токена = _http(503)

    _проход(google)

    assert "i1" in база.стоит, "событие снять не удалось — запись нужна до следующего прохода"
    google.сбой_токена = None
    итог = _проход(google)
    assert итог.deleted == 1 and google.календарь == {} and "i1" not in база.стоит


def test_мёртвый_доступ_запись_об_осиротевшем_событии_забывает(база: База, google: Google) -> None:
    база.добавить("i1", date(2026, 11, 6))
    _проход(google)
    база.снять("i1")
    google.сбой_токена = _http(400, {"error": "invalid_grant"})

    _проход(google)

    assert "i1" not in база.стоит
