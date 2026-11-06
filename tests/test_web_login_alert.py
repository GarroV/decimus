"""Сообщение владельцу о входе главного админа (D720): кому, когда и что не ломает вход."""

from __future__ import annotations

import urllib.error
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.web import login_alert
from src.web.login_alert import compose, device, notify_login

CHANNEL = {"FURCA_NOTIFY_URL": "https://канал.example", "FURCA_SECRET": "ключ-канала"}
MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
OWNER = SimpleNamespace(role="superadmin", login="garva")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[str, str], str, str]]:
    out: list[tuple[tuple[str, str], str, str]] = []
    monkeypatch.setattr(login_alert.furca, "send", lambda *a: out.append(a))
    return out


def _notify(account: object, env: dict[str, str]) -> bool:
    return notify_login(
        account, method="google", ip="203.0.113.7", user_agent=MAC, env=env, background=False
    )


def test_главному_админу_уходит_одно_сообщение(sent: list) -> None:
    assert _notify(OWNER, CHANNEL) is True

    assert len(sent) == 1
    target, text, kind = sent[0]
    assert target == ("https://канал.example/notify", "ключ-канала") and kind == "alert"
    assert "garva через Google" in text and "Chrome на macOS" in text and "203.0.113.7" in text


@pytest.mark.parametrize("роль", ["admin", "developer", "auditor", "control"])
def test_остальным_ролям_сообщения_нет(sent: list, роль: str) -> None:
    assert _notify(SimpleNamespace(role=роль, login="x"), CHANNEL) is False
    assert sent == []


def test_без_канала_и_в_демо_ничего_не_уходит(sent: list) -> None:
    assert _notify(OWNER, {}) is False
    assert _notify(OWNER, {**CHANNEL, "WEB_DEMO": "1"}) is False
    assert sent == []


def test_сбой_канала_вход_не_ломает(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    def упасть(*_a: object) -> None:
        raise urllib.error.URLError("канал лежит")

    monkeypatch.setattr(login_alert.furca, "send", упасть)

    assert _notify(OWNER, CHANNEL) is True  # исключения наружу нет
    assert "не ушло" in caplog.text


def test_текст_с_ссылкой_на_выход_везде() -> None:
    text = compose(
        login="garva",
        method="passkey",
        ip=None,
        user_agent=None,
        moment=datetime(2026, 11, 6, 9, 5, tzinfo=UTC),
        base_url="https://decimus.example",
    )

    assert text == (
        "Вход в админку Decimus: garva ключом доступа.\n"
        "устройство неизвестно, адрес неизвестен, 06.11 09:05 UTC.\n"
        "Если это не вы — выйти везде: https://decimus.example/settings?tile=signout"
    )


def test_устройство_опознаётся_коротко() -> None:
    assert device(MAC) == "Chrome на macOS"
    assert device(MAC.replace("Chrome/130.0.0.0 Safari", "Edg/130 Safari")) == "Edge на macOS"
    assert device("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Version/18 Safari/604") == (
        "Safari на iPhone"
    )
    assert device("curl/8") == "curl/8"
