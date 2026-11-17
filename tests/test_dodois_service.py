"""Продление, проверка и запись входа Dodo IS (D640b) на двойнике хранилища.

Главное, что держит набор: ключ продления одноразовый, поэтому новая пара пишется атомарно,
упавшая запись не теряет вход молча, а отказ в продлении помечает вход истёкшим и ничего не
стирает. Настоящая транзакция — `tests/test_db_dodois_logins.py` (нужна база).
"""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
        if поля.get("expect_linked_at") != self.входы[поля["country"]].linked_at:
            raise store.LoginSuperseded("Synthetic relink")
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

    def set_account(
        self,
        country: str,
        name: str | None,
        email: str | None,
        *,
        expect_linked_at=None,
    ) -> None:
        if expect_linked_at is not None and self.входы[country].linked_at != expect_linked_at:
            return
        self.входы[country] = replace(self.входы[country], account_name=name, account_email=email)

    def record_state(self, country: str, state: str, reason: str | None, **поля: Any) -> None:
        if (
            поля.get("expect_linked_at") is not None
            and self.входы[country].linked_at != поля["expect_linked_at"]
        ):
            return
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


@pytest.fixture(autouse=True)
def _чисто(domain_env, monkeypatch) -> Any:
    monkeypatch.setenv("SECRETS_KEY", base64.b64encode(os.urandom(32)).decode())
    Path(os.environ["STATE_DIR"]).mkdir(parents=True, exist_ok=True)
    service.forget_unwritten()
    yield
    service.forget_unwritten()


@pytest.fixture
def база(monkeypatch: pytest.MonkeyPatch) -> Хранилище:
    двойник = Хранилище()
    for имя in (
        "get_login",
        "list_logins",
        "read_tokens",
        "replace_tokens",
        "record_state",
        "set_account",
    ):
        monkeypatch.setattr(store, имя, getattr(двойник, имя))
    monkeypatch.setattr(client, "userinfo", lambda *_a: (None, None))
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


def test_незаписанная_пара_повторяется_заходами_и_к_dodois_за_новой_не_ходим(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: убрать `retry_unwritten` из `run_pass` — второй заход снова зовёт
    # продление мёртвым ключом, и вход станет «истёк».
    зовы = _продление(monkeypatch, НОВАЯ)
    _счёт(monkeypatch, 4, 4)
    monkeypatch.setattr(service, "credentials", lambda: КЛЮЧИ)
    база.падает_запись = 99
    service.run_pass(now=СЕЙЧАС, sleep=lambda _s: None)
    assert зовы == [СТАРАЯ.refresh]
    assert база.входы["SI"].state == rules.FAILED and база.входы["SI"].reason == "write_failed"

    service.run_pass(now=СЕЙЧАС + timedelta(hours=1), sleep=lambda _s: None)
    assert зовы == [СТАРАЯ.refresh], "за новой парой сходили повторно: ключ продления мёртв"
    assert база.входы["SI"].state == rules.FAILED, "ожидали «запись не легла», не «истёк»"
    assert база.ключи["SI"] == СТАРАЯ

    база.падает_запись = 0
    service.run_pass(now=СЕЙЧАС + timedelta(hours=2), sleep=lambda _s: None)
    assert зовы == [СТАРАЯ.refresh]
    assert база.ключи["SI"] == store.Tokens(НОВАЯ.access, НОВАЯ.refresh), "пара так и не легла"
    assert база.входы["SI"].state == rules.OK
    записей = база.записей_пары
    service.run_pass(now=СЕЙЧАС + timedelta(hours=3), sleep=lambda _s: None)
    assert база.записей_пары == записей, "лишние записи после успеха"


def test_пара_вытесненного_входа_отбрасывается_без_записи_и_без_сбоя(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    _продление(monkeypatch, НОВАЯ)
    база.падает_запись = 99
    service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _s: None)

    def заменён(**_п: Any) -> None:
        raise store.LoginSuperseded("заменён")

    monkeypatch.setattr(store, "replace_tokens", заменён)
    assert service.retry_unwritten(база.входы["SI"], now=СЕЙЧАС) is True
    assert service.retry_unwritten(база.входы["SI"], now=СЕЙЧАС) is None, "пара не забыта"


def _учётка(
    monkeypatch: pytest.MonkeyPatch, итог: tuple[str | None, str | None] | Exception
) -> list[str]:
    зовы: list[str] = []

    def спросить(_contour: str, access: str) -> tuple[str | None, str | None]:
        зовы.append(access)
        if isinstance(итог, Exception):
            raise итог
        return итог

    monkeypatch.setattr(client, "userinfo", спросить)
    return зовы


def test_проверка_дозаполняет_учётку_у_входа_без_неё(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    _счёт(monkeypatch, 10, 10)
    зовы = _учётка(monkeypatch, ("Ana Novak", "ana@example.com"))
    вход = service.check("SI", now=СЕЙЧАС)
    assert вход is not None
    assert (вход.account_name, вход.account_email) == ("Ana Novak", "ana@example.com")
    assert зовы == [СТАРАЯ.access]


def test_проверка_не_спрашивает_учётку_когда_она_есть(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    база.входы["SI"] = _вход(account_email="ana@example.com")
    _счёт(monkeypatch, 10, 10)
    зовы = _учётка(monkeypatch, ("Другой", "x@example.com"))
    вход = service.check("SI", now=СЕЙЧАС)
    assert зовы == []
    assert вход is not None and вход.account_name is None


def test_сбой_записи_учётки_не_ломает_проверку(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    _счёт(monkeypatch, 10, 10)
    _учётка(monkeypatch, ("Ana Novak", None))

    def падает(*_a: Any, **_kwargs: Any) -> None:
        raise AccessError("база отказала")

    monkeypatch.setattr(store, "set_account", падает)
    вход = service.check("SI", now=СЕЙЧАС)
    assert вход is not None
    assert (вход.state, вход.account_name) == (rules.OK, None)


def test_пустой_ответ_userinfo_оставляет_учётку_неизвестной(
    база: Хранилище, monkeypatch: pytest.MonkeyPatch
) -> None:
    _счёт(monkeypatch, 10, 10)
    _учётка(monkeypatch, (None, None))
    вход = service.check("SI", now=СЕЙЧАС)
    assert вход is not None
    assert (вход.state, вход.account_name, вход.account_email) == (rules.OK, None, None)


def test_rotated_pair_survives_process_memory_loss(база, monkeypatch):
    calls = _продление(monkeypatch, НОВАЯ)
    _счёт(monkeypatch, 4, 4)
    monkeypatch.setattr(service, "credentials", lambda: КЛЮЧИ)
    база.падает_запись = 99
    service.run_pass(now=СЕЙЧАС, sleep=lambda _: None)
    service.forget_unwritten()
    база.падает_запись = 0
    service.run_pass(now=СЕЙЧАС + timedelta(hours=1), sleep=lambda _: None)
    assert calls == [СТАРАЯ.refresh]
    assert база.ключи["SI"] == store.Tokens(НОВАЯ.access, НОВАЯ.refresh)
    assert база.входы["SI"].state == rules.OK


def test_pending_pair_is_encrypted_private_and_readable_by_fresh_process(база, monkeypatch):
    import stat
    import subprocess
    import sys

    from src.dodois import refresh_outbox as outbox

    _продление(monkeypatch, НОВАЯ)
    база.падает_запись = 99
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _: None)
    path = Path(os.environ["STATE_DIR"]) / outbox.DIRECTORY / "SI.bin"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    blob = path.read_bytes()
    for value in (НОВАЯ.access, НОВАЯ.refresh, СТАРАЯ.refresh):
        assert value.encode() not in blob
    script = """
from src.dodois.refresh_outbox import locked
with locked('SI') as journal:
    held = journal.read()
    assert held.pair.refresh == 'new-refresh-DDDD'
print('recovered')
"""
    result = subprocess.run(  # noqa: S603 -- fixed interpreter and synthetic script
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.stdout.strip() == "recovered"


@pytest.mark.parametrize("failure", ["state_missing", "key_missing", "fsync_failed"])
def test_unwritable_handoff_refuses_before_provider(база, monkeypatch, failure, tmp_path):
    from src.dodois import refresh_outbox as outbox

    calls = _продление(monkeypatch, НОВАЯ)
    if failure == "state_missing":
        monkeypatch.setenv("STATE_DIR", str(tmp_path / "missing"))
    elif failure == "key_missing":
        monkeypatch.delenv("SECRETS_KEY")
    else:

        def failed(*args):
            raise OSError("Synthetic fsync failure")

        monkeypatch.setattr(outbox.os, "fsync", failed)
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _: None)
    assert not calls
    assert база.ключи["SI"] == СТАРАЯ


def test_uncertain_response_is_not_retried_after_restart(база, monkeypatch):
    calls = _продление(monkeypatch, DodoisError(client.NETWORK))
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС)
    service.forget_unwritten()
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС + timedelta(hours=1))
    assert calls == [СТАРАЯ.refresh]
    assert база.входы["SI"].state == rules.FAILED
    assert база.входы["SI"].reason == "network"


def test_failed_ready_write_does_not_reuse_rotated_token_after_restart(база, monkeypatch):
    from src.dodois import refresh_outbox as outbox

    calls = _продление(monkeypatch, НОВАЯ)
    original = outbox.Journal.write

    def fail_ready(self, pending):
        if pending.pair is not None:
            raise OSError("Synthetic ready persistence failure")
        original(self, pending)

    monkeypatch.setattr(outbox.Journal, "write", fail_ready)
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС)
    assert база.записей_пары == 0
    service.forget_unwritten()
    monkeypatch.setattr(outbox.Journal, "write", original)
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС + timedelta(hours=1))
    assert calls == [СТАРАЯ.refresh]
    assert база.входы["SI"].state != rules.EXPIRED


@pytest.mark.parametrize("response", [НОВАЯ, RefreshRejected(), DodoisError(client.NETWORK)])
def test_relinked_login_ignores_late_provider_response(база, monkeypatch, response):
    original = база.входы["SI"]
    replacement = replace(original, linked_at=СЕЙЧАС, state=rules.OK, reason=None)
    new_tokens = store.Tokens("replacement-access", "replacement-refresh")

    def relink(*args):
        база.входы["SI"] = replacement
        база.ключи["SI"] = new_tokens
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client, "refresh_tokens", relink)
    service.refresh(original, КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _: None)
    assert база.входы["SI"] == replacement
    assert база.ключи["SI"] == new_tokens
    service.forget_unwritten()
    service.retry_unwritten(replacement, now=СЕЙЧАС)
    assert база.входы["SI"] == replacement
    assert база.ключи["SI"] == new_tokens


def test_late_check_failure_does_not_change_relinked_login(база, monkeypatch):
    original = база.входы["SI"]
    replacement = replace(original, linked_at=СЕЙЧАС, state=rules.OK, reason=None)
    monkeypatch.setattr(client, "working_pizzerias", lambda _: ["synthetic-unit"])

    def failed(*args):
        база.входы["SI"] = replacement
        raise DodoisError(client.NETWORK)

    monkeypatch.setattr(client, "count_open", failed)
    service.check("SI", now=СЕЙЧАС)
    assert база.входы["SI"] == replacement


def test_country_lock_blocks_another_process(база):
    import subprocess
    import sys

    from src.dodois import refresh_outbox as outbox

    script = """
from src.dodois import refresh_outbox as outbox
outbox.LOCK_TIMEOUT_SECONDS = 0.1
try:
    with outbox.locked('SI'):
        raise AssertionError('Concurrent provider refresh would be allowed')
except outbox.OutboxError:
    print('blocked')
"""
    with outbox.locked("SI"):
        result = subprocess.run(  # noqa: S603 -- fixed interpreter and synthetic script
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[1],
        )
    assert result.stdout.strip() == "blocked"


def test_concurrent_refresh_uses_source_token_only_once(база, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    entered, release = Event(), Event()
    calls = []
    source = база.входы["SI"]

    def provider(*args):
        calls.append(args[-1])
        entered.set()
        assert release.wait(5)
        return НОВАЯ

    monkeypatch.setattr(client, "refresh_tokens", provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.refresh, source, КЛЮЧИ, now=СЕЙЧАС)
        assert entered.wait(5)
        second = pool.submit(service.refresh, source, КЛЮЧИ, now=СЕЙЧАС)
        release.set()
        assert first.result(timeout=10)
        assert second.result(timeout=10)
    assert calls == [СТАРАЯ.refresh]


def test_stale_process_cache_cannot_delete_another_process_ready_pair(база, monkeypatch):
    from src.dodois import refresh_outbox as outbox

    _продление(monkeypatch, НОВАЯ)
    база.падает_запись = 99
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _: None)
    assert service._unwritten
    replacement = replace(база.входы["SI"], linked_at=СЕЙЧАС)
    база.входы["SI"] = replacement
    newer = TokenPair("newer-access", "newer-refresh", 86400, "openid sales")
    with outbox.locked("SI") as journal:
        journal.write(
            outbox.Pending(
                "SI",
                "intl",
                replacement.linked_at,
                СЕЙЧАС + timedelta(minutes=1),
                service._source_hash("replacement-refresh"),
                newer,
            )
        )
    база.падает_запись = 0
    assert service.retry_unwritten(replacement, now=СЕЙЧАС, sleep=lambda _: None)
    assert база.ключи["SI"] == store.Tokens(newer.access, newer.refresh)


@pytest.mark.parametrize("country", ["../SI", "SI/../../x", "si", "", "SLO"])
def test_country_cannot_escape_outbox(country):
    from src.dodois import refresh_outbox as outbox

    with pytest.raises(outbox.OutboxError):
        with outbox.locked(country):
            pytest.fail("Invalid country acquired a refresh lock")


@pytest.mark.parametrize("damage", ["ciphertext", "key", "country"])
def test_pending_authentication_failure_never_calls_provider(база, monkeypatch, damage):
    from src.dodois import refresh_outbox as outbox

    calls = _продление(monkeypatch, НОВАЯ)
    база.падает_запись = 99
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС, sleep=lambda _: None)
    service.forget_unwritten()
    root = Path(os.environ["STATE_DIR"]) / outbox.DIRECTORY
    path = root / "SI.bin"
    if damage == "ciphertext":
        blob = bytearray(path.read_bytes())
        blob[-1] ^= 1
        path.write_bytes(blob)
    elif damage == "key":
        monkeypatch.setenv("SECRETS_KEY", base64.b64encode(os.urandom(32)).decode())
    else:
        (root / "RS.bin").write_bytes(path.read_bytes())
        with outbox.locked("RS") as journal:
            with pytest.raises(outbox.OutboxError):
                journal.read()
        return
    assert not service.refresh(база.входы["SI"], КЛЮЧИ, now=СЕЙЧАС + timedelta(hours=1))
    assert calls == [СТАРАЯ.refresh]
