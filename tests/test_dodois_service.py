"""Продление, проверка и запись входа Dodo IS (D640) на двойнике хранилища.

Главное, что держит набор: ключ продления одноразовый, поэтому новая пара пишется атомарно,
упавшая запись не теряет вход молча, а отказ в продлении помечает вход истёкшим и ничего не
стирает. Настоящая транзакция — `tests/test_db_dodois_logins.py` (нужна база).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.db import dodois_logins as store
from src.db.errors import AccessError
from src.dodois import client, service
from src.dodois.client import Credentials, DodoisError, RefreshRejected, TokenPair
from src.domain import dodois as rules
from src.domain.dodois import Login

СЕЙЧАС = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)  # ночь: окно продления открыто
КЛЮЧИ = Credentials("app-id", "app-secret")
СТАРАЯ = store.Tokens("old-access-AAAA", "old-refresh-BBBB")
НОВАЯ = TokenPair("new-access-CCCC", "new-refresh-DDDD", 86400, "openid sales")


def _вход(**поля: Any) -> Login:
    основа: dict[str, Any] = {
        "country": "SI",
        "contour": "intl",
        "source": "invite",
        "issued_by": "director",
        "account_name": None,
        "account_email": None,
        "linked_at": СЕЙЧАС - timedelta(days=3),
        "scope": rules.SCOPES,
        "units_total": 10,
        "units_open": 10,
        "refreshed_at": СЕЙЧАС - timedelta(hours=24),
        "access_expires_at": СЕЙЧАС,
        "checked_at": СЕЙЧАС - timedelta(hours=1),
        "state": rules.OK,
        "reason": None,
    }
    return Login(**{**основа, **поля})


class Хранилище:
    """Двойник `dodois_logins`: входы и пара ключей в памяти; запись можно ронять."""

    def __init__(self) -> None:
        self.входы: dict[str, Login] = {"SI": _вход()}
        self.ключи: dict[str, store.Tokens] = {"SI": СТАРАЯ}
        self.падает_запись = 0  # сколько ближайших записей пары уронить
        self.записей_пары = 0
        self.состояния: list[tuple[str, str, str | None]] = []

    def get_login(self, country: str) -> Login | None:
        return self.входы.get(country)

    def list_logins(self) -> tuple[Login, ...]:
        return tuple(self.входы.values())

    def read_tokens(self, country: str) -> store.Tokens | None:
        return self.ключи.get(country)

    def replace_tokens(self, **поля: Any) -> None:
        self.записей_пары += 1
        if self.падает_запись > 0:
            self.падает_запись -= 1
            raise AccessError("база отказала")  # транзакция откатилась: ничего не изменено
        self.ключи[поля["country"]] = поля["tokens"]
        self.входы[поля["country"]] = replace(
            self.входы[поля["country"]],
            refreshed_at=поля["now"],
            access_expires_at=поля["access_expires_at"],
        )

    def record_state(self, country: str, state: str, reason: str | None, **поля: Any) -> None:
        self.состояния.append((country, state, reason))
        вход = self.входы[country]
        self.входы[country] = replace(
            вход,
            state=state,
            reason=reason,
            checked_at=поля["now"],
            units_total=вход.units_total
            if поля.get("units_total") is None
            else поля["units_total"],
            units_open=вход.units_open if поля.get("units_open") is None else поля["units_open"],
        )


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> Хранилище:
    двойник = Хранилище()
    for имя in ("get_login", "list_logins", "read_tokens", "replace_tokens", "record_state"):
        monkeypatch.setattr(store, имя, getattr(двойник, имя))
    return двойник


def _продление(monkeypatch: pytest.MonkeyPatch, итог: TokenPair | Exception) -> list[str]:
    зовы: list[str] = []

    def продлить(_creds: Credentials, _contour: str, refresh_token: str) -> TokenPair:
        зовы.append(refresh_token)
        if isinstance(итог, Exception):
            raise итог
        return итог

    monkeypatch.setattr(client, "refresh_tokens", продлить)
    return зовы


def test_продление_кладёт_новую_пару_и_отмечает_время(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    зовы = _продление(monkeypatch, НОВАЯ)
    assert service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _s: None) is True
    assert зовы == [СТАРАЯ.refresh], "продление шло прежним ключом продления"
    assert база.ключи["SI"] == store.Tokens(НОВАЯ.access, НОВАЯ.refresh)
    assert база.входы["SI"].refreshed_at == СЕЙЧАС
    assert база.входы["SI"].access_expires_at == СЕЙЧАС + timedelta(seconds=86400)


def test_упавшая_запись_пробуется_снова_с_той_же_парой(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: `WRITE_TRIES = 1` — одна упавшая запись теряет вход, тест падает.
    _продление(monkeypatch, НОВАЯ)
    база.падает_запись = 2
    assert service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _s: None) is True
    assert база.записей_пары == 3
    assert база.ключи["SI"].refresh == НОВАЯ.refresh


def test_запись_не_легла_совсем_состояние_сбой_и_старая_пара_цела(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Сломанная копия: не звать `_note(... "write_failed")` — состояние остаётся «работает».
    _продление(monkeypatch, НОВАЯ)
    база.падает_запись = 99
    with caplog.at_level("DEBUG"):
        сделано = service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _s: None)
    assert сделано is False
    assert база.записей_пары == service.WRITE_TRIES
    assert база.ключи["SI"] == СТАРАЯ, "упавшая запись не должна менять пару"
    assert база.состояния[-1] == ("SI", rules.FAILED, "write_failed")
    for значение in (НОВАЯ.access, НОВАЯ.refresh, СТАРАЯ.access, СТАРАЯ.refresh):
        assert значение not in caplog.text, "значение ключа попало в журнал процесса"


def test_отказ_в_продлении_вход_истёк_и_пара_не_стёрта(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    _продление(monkeypatch, RefreshRejected())
    assert service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС) is False
    assert база.состояния[-1] == ("SI", rules.EXPIRED, "refresh_rejected")
    assert база.ключи["SI"] == СТАРАЯ and база.записей_пары == 0


def test_сбой_связи_при_продлении_не_делает_вход_истёкшим(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: ловить `DodoisError` до `RefreshRejected` — сбой связи «убьёт» вход.
    _продление(monkeypatch, DodoisError(client.NETWORK))
    assert service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС) is False
    assert база.состояния[-1] == ("SI", rules.FAILED, "network")


def test_вход_заменён_за_время_продления_это_не_сбой(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    _продление(monkeypatch, НОВАЯ)

    def заменён(**_поля: Any) -> None:
        raise store.LoginSuperseded("заменён")

    monkeypatch.setattr(store, "replace_tokens", заменён)
    assert service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС) is True
    assert база.состояния == []


def _счёт(monkeypatch: pytest.MonkeyPatch, всего: int, открыто: int) -> None:
    monkeypatch.setattr(client, "working_pizzerias", lambda _c: [f"u{n}" for n in range(всего)])
    monkeypatch.setattr(client, "count_open", lambda *_a, **_k: открыто)


@pytest.mark.parametrize(
    ("всего", "открыто", "состояние"),
    [(10, 10, rules.OK), (10, 6, rules.PARTIAL), (0, 0, rules.FAILED)],
)
def test_проверка_пишет_x_из_y_и_состояние(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch, всего: int, открыто: int, состояние: str
) -> None:
    _счёт(monkeypatch, всего, открыто)
    вход = service.check("SI", now=СЕЙЧАС)
    assert вход is not None
    assert (вход.state, вход.units_total, вход.units_open) == (состояние, всего, открыто)


def test_сбой_связи_при_проверке_счёт_не_затирается(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    def падает(_c: str) -> list[str]:
        raise DodoisError(client.RATE_LIMITED)

    monkeypatch.setattr(client, "working_pizzerias", падает)
    вход = service.check("SI", now=СЕЙЧАС)
    assert вход is not None
    assert (вход.state, вход.reason) == (rules.FAILED, "rate_limited")
    assert (вход.units_total, вход.units_open) == (10, 10)


def test_истёкший_вход_не_проверяется_мёртвым_ключом(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    база.входы["SI"] = _вход(state=rules.EXPIRED, reason="refresh_rejected")
    вызвано: list[str] = []
    monkeypatch.setattr(client, "working_pizzerias", lambda c: вызвано.append(c) or [])
    service.check("SI", now=СЕЙЧАС)
    assert вызвано == []


def test_заход_бота_ночью_продлевает_потом_проверяет(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    зовы = _продление(monkeypatch, НОВАЯ)
    _счёт(monkeypatch, 4, 4)
    monkeypatch.setattr(service, "credentials", lambda: КЛЮЧИ)
    service.run_pass(now=СЕЙЧАС, sleep=lambda _s: None)
    assert зовы == [СТАРАЯ.refresh]
    assert база.входы["SI"].units_open == 4 and база.входы["SI"].state == rules.OK


def test_днём_свежий_вход_только_проверяется(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    день = СЕЙЧАС.replace(hour=15)
    база.входы["SI"] = _вход(
        refreshed_at=день - timedelta(hours=12), access_expires_at=день + timedelta(hours=12)
    )
    зовы = _продление(monkeypatch, НОВАЯ)
    _счёт(monkeypatch, 3, 3)
    monkeypatch.setattr(service, "credentials", lambda: КЛЮЧИ)
    service.run_pass(now=день)
    assert зовы == [] and база.входы["SI"].units_total == 3


def test_нет_ключей_приложения_вход_помечается_сбоем_без_падения(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    зовы = _продление(monkeypatch, НОВАЯ)
    monkeypatch.setattr(service, "credentials", lambda: None)
    service.run_pass(now=СЕЙЧАС)
    assert зовы == []
    assert база.состояния[-1] == ("SI", rules.FAILED, "no_keys")


def test_истёкший_вход_заходом_не_продлевается(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    база.входы["SI"] = _вход(state=rules.EXPIRED, reason="refresh_rejected")
    зовы = _продление(monkeypatch, НОВАЯ)
    monkeypatch.setattr(service, "credentials", lambda: КЛЮЧИ)
    service.run_pass(now=СЕЙЧАС)
    assert зовы == [], "отвергнутый ключ продления не дёргаем каждый час"
