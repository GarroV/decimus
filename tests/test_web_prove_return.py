"""Возврат после подтверждения второго шага (D670): куда ведёт верный код и что не принимается.

Ядро безопасности — открытый редирект: путь возврата принимается только свой и допустимый
(`reauth.safe_back`), чужой адрес даёт прежнее поведение — экран защиты. База подменена на
границе модуля `second_step`; настоящая ступень — `tests/test_web_second_factor_journeys.py`.
Сломанная копия: заменить `prove_return.checked` на `return raw or ""` — падают тесты чужих адресов.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from flask.testing import FlaskClient
from web_harness import СВОЙ, Сессия, войти, подменить_двери, собрать

from src.db import second_factor as store
from src.domain.second_factor import new_backup_codes
from src.web import auth, second_step, security_screen

ЗАГОЛОВКИ = {"Origin": СВОЙ}
ЗАЩИТА = "/settings/security"
ВКЛАДКА = "/administration?tab=dodois&country=AM"
КОД = new_backup_codes(1)[0]


@pytest.fixture
def клиент(monkeypatch: pytest.MonkeyPatch) -> Iterator[FlaskClient]:
    подменить_двери(monkeypatch, tenant="HQ", role="superadmin")
    прежняя = auth.resolve_session

    def _resolve(token: str) -> Any:
        учётка = прежняя(token)
        учётка.passed_second_step = False
        return учётка

    monkeypatch.setattr(auth, "resolve_session", _resolve)
    статус = SimpleNamespace(
        passkeys=(), totp_confirmed=False, totp_pending=False, backup_left=3, has_factor=True
    )
    monkeypatch.setattr(store, "status_of", lambda _user: статус)
    monkeypatch.setattr(store, "use_backup_code", lambda _user, отпечаток: отпечаток is not None)
    monkeypatch.setattr(store, "factors_all_newer_than", lambda _user, _since: False)
    monkeypatch.setattr(second_step, "open_session", lambda *_a, **_k: Сессия())
    monkeypatch.setattr(second_step, "close_session", lambda _token: True)
    monkeypatch.setattr(
        second_step,
        "admit_attempt",
        lambda **_k: SimpleNamespace(
            admitted=True, verdict=SimpleNamespace(retry_after_minutes=None, retry_after_seconds=0)
        ),
    )
    monkeypatch.setattr(second_step, "note_success", lambda **_k: None)
    with собрать(tenant="HQ").test_client() as c:
        assert войти(c).status_code == 302
        yield c


def _доказать(клиент: FlaskClient, **форма: str) -> Any:
    return клиент.post(f"{ЗАЩИТА}/prove", data={"code": КОД, **форма}, headers=ЗАГОЛОВКИ)


def test_верный_код_с_путём_возврата_ведёт_на_него(клиент: FlaskClient) -> None:
    ответ = _доказать(клиент, next=ВКЛАДКА)
    assert ответ.status_code == 302
    assert ответ.headers["Location"] == ВКЛАДКА


@pytest.mark.parametrize(
    "чужой",
    ["//evil.com", "https://evil.com", "/\\evil.com", "/login"],
)
def test_чужой_или_недопустимый_путь_даёт_экран_защиты(клиент: FlaskClient, чужой: str) -> None:
    ответ = _доказать(клиент, next=чужой)
    assert ответ.status_code == 302
    assert ответ.headers["Location"] == f"{ЗАЩИТА}?proved=1"


def test_неверный_код_оставляет_путь_возврата_и_страница_несёт_его_в_форме(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store, "use_backup_code", lambda _user, _отпечаток: False)
    ответ = _доказать(клиент, next=ВКЛАДКА)
    assert ответ.status_code == 302
    адрес = ответ.headers["Location"]
    assert adres_ok(адрес)
    страница = клиент.get(адрес).get_data(as_text=True)
    assert f'name="next" value="{ВКЛАДКА}"'.replace("&", "&amp;") in страница


def adres_ok(адрес: str) -> bool:
    return адрес.startswith(f"{ЗАЩИТА}?prove=bad&next=%2Fadministration%3Ftab%3Ddodois")


def test_чужой_путь_не_попадает_в_форму_страницы(клиент: FlaskClient) -> None:
    страница = клиент.get(f"{ЗАЩИТА}?next=//evil.com").get_data(as_text=True)
    assert 'id="prove"' in страница  # форма подтверждения на месте
    assert 'value="//evil.com"' not in страница  # …но без чужого пути


def _давно_вошёл(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сессия старше окна подключения способов: так выглядит вход через Google час назад."""
    прежняя = auth.resolve_session

    def _resolve(token: str) -> Any:
        учётка = прежняя(token)
        учётка.signed_in_at = datetime.now(UTC) - timedelta(hours=3)
        return учётка

    monkeypatch.setattr(auth, "resolve_session", _resolve)


def test_весь_путь_подтверждения_ключей_сервисов_через_устаревший_вход_возвращает_на_вкладку(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ломали: у устаревшего входа вместо карточки подтверждения стояло «Войти заново»
    без пути возврата — человека выбрасывало на вход, а не на вкладку, откуда он пришёл.
    Сломанная копия: вернуть `{% if not fresh %}` без `show_prove` — падает на `id="prove"`."""
    _давно_вошёл(monkeypatch)
    # 1. «Вход и защита» по ссылке отказа: карточка подтверждения на месте и несёт путь
    адрес = f"{ЗАЩИТА}?next=%2Fadministration%3Ftab%3Ddodois%26country%3DAM"
    ответ = клиент.get(адрес)
    защита = ответ.get_data(as_text=True)
    assert 'id="prove"' in защита and "relogin" not in защита
    assert f'name="next" value="{ВКЛАДКА}"'.replace("&", "&amp;") in защита
    # 2. верный код возвращает на ту же вкладку и страну
    assert _доказать(клиент, next=ВКЛАДКА).headers["Location"] == ВКЛАДКА


def test_войти_заново_у_устаревшего_входа_несёт_путь_возврата(
    клиент: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _давно_вошёл(monkeypatch)
    monkeypatch.setattr(security_screen, "close_session", lambda _token: True)
    возврат = "/administration?tab=dodois&country=TR"
    ответ = клиент.post(f"{ЗАЩИТА}/relogin", data={"next": возврат}, headers=ЗАГОЛОВКИ)
    адрес = urlsplit(ответ.headers["Location"])
    assert parse_qs(адрес.query)["next"] == [возврат]
    # чужой путь не принимается
    чужой = клиент.post(f"{ЗАЩИТА}/relogin", data={"next": "//evil.com"}, headers=ЗАГОЛОВКИ)
    assert "evil" not in чужой.headers["Location"]
