"""Google Календарь из «Настроек» (D740, D741, #1590): согласие, чей доступ, кнопки.

Сети нет: обмен кода — двойник, база — двойник. Проверяется то, что делаем МЫ: какие права
и какой режим доступа просим, чей аккаунт принимаем, что сохраняем и что видит человек.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, Учётка, войти, подменить_двери, собрать

from src.db import calendar_store
from src.db.errors import AccessError
from src.gcal import client as gcal_client
from src.gcal import grant as gcal_grant
from src.web import auth, calendar_connect, google_link
from src.web.google_auth import GoogleSettings

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ПОЧТА = "director@dodobrands.io"
КЛИЕНТ = "наш-клиент.apps.googleusercontent.com"
РЕКВИЗИТЫ = GoogleSettings(
    client_id=КЛИЕНТ,
    client_secret="секрет-набора",
    redirect_uri="https://стенд.example/auth/google/callback",
)


class Обмен:
    """Двойник обмена кода: отдаёт то, что «сказал Google», с `nonce` из ухода."""

    def __init__(self) -> None:
        self.nonce = ""
        self.почта = ПОЧТА
        self.scopes = frozenset({"openid", "email", gcal_client.EVENTS_SCOPE})
        self.sub = "110169484474386276334"
        self.refresh = "долгий-ключ"
        self.сбой = False

    def __call__(self, settings: GoogleSettings, *, code: str) -> calendar_connect.CalendarConsent:
        if self.сбой:
            raise calendar_connect.CalendarConsentError("invalid_grant")
        return calendar_connect.CalendarConsent(
            refresh_token=self.refresh,
            email=self.почта,
            subject=self.sub,
            nonce=self.nonce,
            scopes=self.scopes,
        )


class База:
    def __init__(self) -> None:
        self.сохранено: list[dict[str, str]] = []
        self.подключение: calendar_store.Grant | None = None
        self.проверка_sub = "ok"
        self.старый: str | None = None

    def refresh_token_of(self, user_id: str) -> str | None:
        return self.старый

    def save_grant(
        self, user_id: str, *, google_email: str, scope: str, refresh_token: str
    ) -> None:
        self.сохранено.append({"email": google_email, "scope": scope, "key": refresh_token})

    def grant_of(self, user_id: str) -> calendar_store.Grant | None:
        return self.подключение


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> База:
    двойник = База()
    monkeypatch.setattr(calendar_store, "save_grant", двойник.save_grant)
    monkeypatch.setattr(calendar_store, "grant_of", двойник.grant_of)
    monkeypatch.setattr(calendar_store, "refresh_token_of", двойник.refresh_token_of)
    monkeypatch.setattr(
        calendar_connect, "claim_google_sub", lambda *_a, **_k: двойник.проверка_sub
    )
    return двойник


@pytest.fixture
def обмен(monkeypatch: pytest.MonkeyPatch) -> Обмен:
    двойник = Обмен()
    monkeypatch.setattr(calendar_connect, "exchange", двойник)
    return двойник


def _стенд(
    monkeypatch: pytest.MonkeyPatch, *, tenant: str = "HQ", email: str | None = ПОЧТА
) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant=tenant, role="admin")
    monkeypatch.setattr(auth, "load_google_settings", lambda *_, **__: РЕКВИЗИТЫ)
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: Учётка(
                tenant=tenant, role="admin", email=email, signed_in_at=datetime.now(UTC)
            ),
        )
        yield client


@pytest.fixture
def ук(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    yield from _стенд(monkeypatch)


def начать(client: FlaskClient, обмен: Обмен) -> tuple[str, dict[str, list[str]]]:
    ответ = client.post("/settings/google-calendar", headers=ЗАГОЛОВКИ)
    assert ответ.status_code == 302, ответ.get_data(as_text=True)[:300]
    параметры = parse_qs(urlsplit(ответ.headers["Location"]).query)
    обмен.nonce = параметры["nonce"][0]
    return параметры["state"][0], параметры


def вернуться(client: FlaskClient, метка: str, **ещё: str) -> str:
    запрос = {"state": метка, "code": "код", **ещё}
    ответ = client.get(auth.GOOGLE_CALLBACK_PATH, query_string=запрос)
    assert ответ.status_code == 302, (ответ.status_code, ответ.get_data(as_text=True)[:200])
    return parse_qs(urlsplit(ответ.headers["Location"]).query).get(google_link.RESULT_PARAM, [""])[
        0
    ]


# ── Что просим у Google ─────────────────────────────────────────────────


def test_просим_узкое_право_ключ_продления_и_свежее_согласие(ук: FlaskClient, обмен: Обмен) -> None:
    _, п = начать(ук, обмен)

    assert п["scope"] == [f"openid email {gcal_client.EVENTS_SCOPE}"]
    assert п["access_type"] == ["offline"], "без него Google не выдаст ключ продления"
    assert п["prompt"] == ["consent"], "без него повторное подключение остаётся без ключа"
    assert п["login_hint"] == [ПОЧТА]
    assert "gmail" not in п["scope"][0]


def test_без_привязанной_почты_google_не_уводим(
    monkeypatch: pytest.MonkeyPatch, база: База, обмен: Обмен
) -> None:
    for client in _стенд(monkeypatch, email=None):
        ответ = client.post("/settings/google-calendar", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 302 and "google=calendar_account" in ответ.headers["Location"]


def test_начало_только_со_своей_страницы(ук: FlaskClient) -> None:
    ответ = ук.post("/settings/google-calendar", headers={"Origin": "https://чужой.example"})

    assert ответ.status_code == 403


# ── Возврат: чей доступ ─────────────────────────────────────────────────


def test_свой_аккаунт_ключ_сохраняется(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка, _ = начать(ук, обмен)

    assert вернуться(ук, метка) == "calendar_on"
    assert база.сохранено == [
        {"email": ПОЧТА, "scope": gcal_client.EVENTS_SCOPE, "key": "долгий-ключ"}
    ]


def test_чужой_аккаунт_из_окна_google_отвергается_до_сохранения(
    ук: FlaskClient, база: База, обмен: Обмен
) -> None:
    """F-018 для календаря: событие обязано лечь в календарь вошедшего, а не выбранного в окне."""
    обмен.почта = "other@dodobrands.io"
    метка, _ = начать(ук, обмен)

    assert вернуться(ук, метка) == "calendar_account"
    assert база.сохранено == []


def test_тот_же_адрес_но_другой_аккаунт_google_отвергается(
    ук: FlaskClient, база: База, обмен: Обмен
) -> None:
    база.проверка_sub = "other"
    метка, _ = начать(ук, обмен)

    assert вернуться(ук, метка) == "calendar_account"
    assert база.сохранено == []


def test_снятая_в_окне_галочка_права_на_события_отвергается(
    ук: FlaskClient, база: База, обмен: Обмен
) -> None:
    обмен.scopes = frozenset({"openid", "email"})
    метка, _ = начать(ук, обмен)

    assert вернуться(ук, метка) == "calendar_scope"
    assert база.сохранено == []


def test_nonce_чужого_захода_отвергается(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка, _ = начать(ук, обмен)
    обмен.nonce = "от-другого-захода"

    assert вернуться(ук, метка) == "calendar_failed"
    assert база.сохранено == []


def test_отказ_в_окне_google_не_поломка(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка, _ = начать(ук, обмен)

    assert вернуться(ук, метка, error="access_denied") == "calendar_denied"
    assert база.сохранено == []


def test_сбой_обмена_кода_называется_неудачей(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    метка, _ = начать(ук, обмен)
    обмен.сбой = True

    assert вернуться(ук, метка) == "calendar_failed"


def test_чужая_метка_не_доходит_до_обмена(ук: FlaskClient, база: База, обмен: Обмен) -> None:
    начать(ук, обмен)

    ответ = ук.get(auth.GOOGLE_CALLBACK_PATH, query_string={"state": "подделка", "code": "к"})

    assert ответ.status_code == 401 and база.сохранено == []


# ── Обмен кода: что читаем из ответа Google ─────────────────────────────


def _id_token(**ещё: object) -> str:
    нагрузка: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": КЛИЕНТ,
        "exp": time.time() + 600,
        "email": ПОЧТА,
        "email_verified": True,
        "sub": "110169484474386276334",
        "nonce": "н",
    }
    нагрузка.update(ещё)
    середина = base64.urlsafe_b64encode(json.dumps(нагрузка).encode()).decode().rstrip("=")
    return f"з.{середина}.п"


class _Ответ:
    def __init__(self, тело: dict[str, Any]) -> None:
        self._тело = json.dumps(тело).encode()

    def __enter__(self) -> _Ответ:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._тело


def _обмен_с_ответом(monkeypatch: pytest.MonkeyPatch, тело: dict[str, Any]) -> Any:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda запрос, timeout: _Ответ(тело),
    )
    return calendar_connect.exchange(РЕКВИЗИТЫ, code="код")


def test_обмен_читает_ключ_продления_аккаунт_и_выданные_права(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    итог = _обмен_с_ответом(
        monkeypatch,
        {
            "access_token": "а",
            "refresh_token": "долгий",
            "scope": f"openid email {gcal_client.EVENTS_SCOPE}",
            "id_token": _id_token(),
        },
    )

    assert итог.refresh_token == "долгий" and итог.email == ПОЧТА
    assert gcal_client.EVENTS_SCOPE in итог.scopes and итог.nonce == "н"


def test_обмен_без_ключа_продления_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(calendar_connect.CalendarConsentError) as исход:
        _обмен_с_ответом(monkeypatch, {"access_token": "а", "id_token": _id_token()})
    assert исход.value.code == "no_refresh_token"


def test_обмен_с_токеном_чужого_приложения_отказ(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(calendar_connect.CalendarConsentError):
        _обмен_с_ответом(
            monkeypatch,
            {"refresh_token": "д", "id_token": _id_token(aud="чужой-клиент")},
        )


# ── Кнопки ──────────────────────────────────────────────────────────────


def test_отключение_зовёт_отзыв_и_возвращает_в_настройки(
    ук: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    звали: list[str] = []
    monkeypatch.setattr(
        gcal_grant, "disconnect", lambda user_id: звали.append(user_id) or gcal_grant.OFF
    )

    ответ = ук.post("/settings/google-calendar-off", headers=ЗАГОЛОВКИ)

    assert ответ.status_code == 302 and "google=calendar_off" in ответ.headers["Location"]
    assert len(звали) == 1


def test_неотозванный_ключ_говорит_об_этом(
    ук: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gcal_grant, "disconnect", lambda user_id: gcal_grant.FAILED)

    ответ = ук.post("/settings/google-calendar-off", headers=ЗАГОЛОВКИ)

    assert "google=calendar_revoke" in ответ.headers["Location"]


def test_отключение_только_со_своей_страницы(ук: FlaskClient) -> None:
    ответ = ук.post("/settings/google-calendar-off", headers={"Origin": "https://чужой.example"})

    assert ответ.status_code == 403


def test_база_молчит_при_отключении_человек_видит_это(
    ук: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def упасть(user_id: str) -> str:
        raise AccessError("двойник: база молчит")

    monkeypatch.setattr(gcal_grant, "disconnect", упасть)

    ответ = ук.post("/settings/google-calendar-off", headers=ЗАГОЛОВКИ)

    assert "google=calendar_db" in ответ.headers["Location"]


# ── Экран ───────────────────────────────────────────────────────────────


def test_экран_без_подключения_предлагает_подключить(ук: FlaskClient, база: База) -> None:
    страница = ук.get("/settings?tile=google").get_data(as_text=True)

    assert "/settings/google-calendar?" in страница
    assert "google-calendar-off" not in страница


def test_экран_подключённого_показывает_почту_и_отключение(ук: FlaskClient, база: База) -> None:
    база.подключение = calendar_store.Grant("u", ПОЧТА, gcal_client.EVENTS_SCOPE, None)

    страница = ук.get("/settings?tile=google").get_data(as_text=True)

    assert "google-calendar-off" in страница and ПОЧТА in страница
    assert "переподключите" not in страница


def test_экран_при_сбое_говорит_переподключите(ук: FlaskClient, база: База) -> None:
    база.подключение = calendar_store.Grant("u", ПОЧТА, gcal_client.EVENTS_SCOPE, "invalid_grant")

    страница = ук.get("/settings?tile=google").get_data(as_text=True)

    assert "переподключите" in страница


def test_экран_на_английском(ук: FlaskClient, база: База) -> None:
    страница = ук.get("/settings?tile=google&lang=en").get_data(as_text=True)

    assert "Connect Google Calendar" in страница


def test_партнёру_календарь_не_показывается(monkeypatch: pytest.MonkeyPatch, база: База) -> None:
    for client in _стенд(monkeypatch, tenant="GE"):
        страница = client.get("/settings?tile=google").get_data(as_text=True)

        assert "google-calendar" not in страница


# ── Партнёр: «только УК» держит сервер ──────────────────────────────────


def test_партнёр_не_уводится_к_google_даже_прямым_запросом(
    monkeypatch: pytest.MonkeyPatch, база: База
) -> None:
    for client in _стенд(monkeypatch, tenant="GE"):
        ответ = client.post("/settings/google-calendar", headers=ЗАГОЛОВКИ)

        assert ответ.status_code == 302
        assert "google=calendar_hq" in ответ.headers["Location"]
        assert "accounts.google.com" not in ответ.headers["Location"]


def test_возврат_партнёра_ключ_не_сохраняет(
    monkeypatch: pytest.MonkeyPatch, база: База, обмен: Обмен
) -> None:
    """Кука захода подписана, но учётка партнёра: даже подложенный возврат ничего не пишет."""
    for client in _стенд(monkeypatch, tenant="HQ"):
        метка, _ = начать(client, обмен)
        monkeypatch.setattr(
            auth,
            "resolve_session",
            lambda token: Учётка(
                tenant="GE", role="admin", email=ПОЧТА, signed_in_at=datetime.now(UTC)
            ),
        )

        assert вернуться(client, метка) == "calendar_hq"
        assert база.сохранено == []


# ── Переподключение: прежний ключ отзывается ────────────────────────────


class _Google:
    def __init__(self, *, отзыв_падает: bool = False, новый_жив: bool = True) -> None:
        self.отозвано: list[str] = []
        self.отзыв_падает, self.новый_жив = отзыв_падает, новый_жив

    def revoke(self, token: str) -> None:
        self.отозвано.append(token)
        if self.отзыв_падает:
            raise gcal_client.CalendarError("http_503")

    def access_token(self, keys: object, token: str) -> str:
        if not self.новый_жив:
            raise gcal_client.CalendarError("invalid_grant")
        return "короткий"


def _переподключить(
    ук: FlaskClient, база: База, обмен: Обмен, monkeypatch: pytest.MonkeyPatch, google: _Google
) -> str:
    база.старый = "прежний-ключ"
    monkeypatch.setattr(calendar_connect, "revoke", google.revoke)
    monkeypatch.setattr(calendar_connect, "access_token", google.access_token)
    monkeypatch.setattr(calendar_connect, "keys_from_env", lambda: gcal_client.ClientKeys("к", "с"))
    метка, _ = начать(ук, обмен)
    return вернуться(ук, метка)


def test_переподключение_отзывает_прежний_ключ(
    ук: FlaskClient, база: База, обмен: Обмен, monkeypatch: pytest.MonkeyPatch
) -> None:
    google = _Google()

    assert _переподключить(ук, база, обмен, monkeypatch, google) == "calendar_on"
    assert google.отозвано == ["прежний-ключ"]
    assert [с["key"] for с in база.сохранено] == ["долгий-ключ"]


def test_сбой_отзыва_прежнего_ключа_подключение_не_валит(
    ук: FlaskClient, база: База, обмен: Обмен, monkeypatch: pytest.MonkeyPatch
) -> None:
    google = _Google(отзыв_падает=True)

    assert _переподключить(ук, база, обмен, monkeypatch, google) == "calendar_on"
    assert [с["key"] for с in база.сохранено] == ["долгий-ключ"]


def test_если_отзыв_прежнего_убил_и_новый_ключ_не_сохраняется(
    ук: FlaskClient, база: База, обмен: Обмен, monkeypatch: pytest.MonkeyPatch
) -> None:
    google = _Google(новый_жив=False)

    assert _переподключить(ук, база, обмен, monkeypatch, google) == "calendar_failed"
    assert база.сохранено == []


def test_первое_подключение_ничего_не_отзывает(
    ук: FlaskClient, база: База, обмен: Обмен, monkeypatch: pytest.MonkeyPatch
) -> None:
    google = _Google()
    база.старый = None
    monkeypatch.setattr(calendar_connect, "revoke", google.revoke)
    метка, _ = начать(ук, обмен)

    assert вернуться(ук, метка) == "calendar_on"
    assert google.отозвано == []


def test_ключ_не_открылся_человеку_сказано_отозвать_самому(
    ук: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gcal_grant, "disconnect", lambda user_id: gcal_grant.REVOKE_MANUALLY)

    ответ = ук.post("/settings/google-calendar-off", headers=ЗАГОЛОВКИ)

    assert "google=calendar_manual" in ответ.headers["Location"]
    страница = ук.get(ответ.headers["Location"]).get_data(as_text=True)
    assert "настройках аккаунта Google" in страница
