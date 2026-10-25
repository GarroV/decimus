"""Входы Dodo IS в настоящей базе (D640): шифрованное хранение, атомарная замена пары ключей,
одноразовая ссылка, закрытый список имён в хранилище, права роли приложения.
"""

from __future__ import annotations

import base64
import os
from datetime import UTC, datetime, timedelta

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import dodois_logins as store  # noqa: E402
from src.db import secret_crypto, service_keys, web_throttle  # noqa: E402
from src.db.errors import AccessError  # noqa: E402
from src.domain import dodois as rules  # noqa: E402

pytestmark = requires_db

НОВАЯ = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
ДОСТУП = "ДОСТУП-1111-значение"
ПРОДЛЕНИЕ = "ПРОДЛЕНИЕ-2222-значение"
ХЕШ_ПАРОЛЯ = "scrypt$16384$8$1$c29sdA$aGFzaA"


@pytest.fixture
def база(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(service_keys, "_cache", {})
    return pg_dsn


@pytest.fixture
def автор(база: str) -> str:
    with psycopg.connect(база) as conn:
        conn.execute("insert into tenants (code) values ('HQ') on conflict do nothing")
        строка = conn.execute(
            "insert into web_users (tenant_code, login, password_hash, role) "
            "values ('HQ', 'owner', %s, 'superadmin') returning id::text",
            (ХЕШ_ПАРОЛЯ,),
        ).fetchone()
        conn.commit()
    assert строка is not None
    return str(строка[0])


def _вход(страна: str = "SI", ключи: store.Tokens | None = None, invite_id: int | None = None):
    return store.save_login(
        country=страна,
        contour="intl",
        source="invite",
        issued_by="owner",
        account_name="Иван",
        account_email="i@example.com",
        scope="openid sales",
        tokens=ключи or store.Tokens(ДОСТУП, ПРОДЛЕНИЕ),
        access_expires_at=НОВАЯ + timedelta(days=1),
        now=НОВАЯ,
        invite_id=invite_id,
    )


def _ссылка(база: str, автор: str, страна: str = "SI", хеш: str = "a" * 64) -> int:
    return store.create_invite(
        country=страна,
        token_hash=хеш,
        issued_by="owner",
        issued_by_id=автор,
        issued_by_role="superadmin",
        issued_by_tenant="HQ",
        now=НОВАЯ,
        expires_at=НОВАЯ + timedelta(hours=24),
    )


def test_ключи_в_базе_только_шифртекстом(база: str) -> None:
    # Сломанная копия: `_put_tokens` кладёт value.encode() вместо шифртекста — тест падает.
    _вход()
    with psycopg.connect(база) as conn:
        строки = conn.execute(
            "select name, row(s.*)::text from vault.secrets s where name like 'dodois.%'"
        ).fetchall()
    assert {r[0] for r in строки} == {"dodois.access.si", "dodois.refresh.si"}
    for _, текст in строки:
        assert ДОСТУП not in текст and ПРОДЛЕНИЕ not in текст
    assert store.read_tokens("SI") == store.Tokens(ДОСТУП, ПРОДЛЕНИЕ)


def test_вход_читается_без_ключей_в_строке(база: str) -> None:
    вход = _вход()
    assert (вход.country, вход.state, вход.source) == ("SI", "ok", "invite")
    for поле in vars(вход).values():
        assert ДОСТУП not in str(поле) and ПРОДЛЕНИЕ not in str(поле)
    assert [x.country for x in store.list_logins()] == ["SI"]


def test_ссылка_гасится_один_раз(база: str, автор: str) -> None:
    # Сломанная копия: в `save_login` убрать `and used_at is null` — второй вход проходит.
    номер = _ссылка(база, автор)
    _вход(invite_id=номер)
    with pytest.raises(store.InviteUnusable):
        _вход(ключи=store.Tokens("другой-доступ", "другое-продление"), invite_id=номер)
    assert store.read_tokens("SI") == store.Tokens(ДОСТУП, ПРОДЛЕНИЕ), "второй вход затёр первый"


def test_ссылка_другой_страны_не_гасится(база: str, автор: str) -> None:
    номер = _ссылка(база, автор, "SI")
    with pytest.raises(store.InviteUnusable):
        _вход("BG", invite_id=номер)
    assert store.get_login("BG") is None and store.read_tokens("BG") is None


def test_отозванная_ссылка_не_гасится_и_отзыв_один_раз(база: str, автор: str) -> None:
    номер = _ссылка(база, автор)
    assert store.revoke_invite(номер, НОВАЯ) is True
    assert store.revoke_invite(номер, НОВАЯ) is False
    отозванная = store.get_invite(номер)
    assert отозванная is not None and отозванная.revoked_at == НОВАЯ
    with pytest.raises(store.InviteUnusable):
        _вход(invite_id=номер)
    assert store.get_login("SI") is None, "отказ оставил половину записи"


def test_ссылка_находится_по_хэшу_и_не_хранит_токен(база: str, автор: str) -> None:
    номер = _ссылка(база, автор, хеш="b" * 64)
    найдена = store.find_invite("b" * 64)
    assert найдена is not None and найдена.id == номер
    assert store.find_invite("c" * 64) is None


def test_замена_пары_атомарна(база: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Сломанная копия: писать логин отдельной транзакцией до ключей — сбой оставит пару наполовину.
    вход = _вход()
    новые = store.Tokens("НОВЫЙ-доступ", "НОВОЕ-продление")
    original = secret_crypto.encrypt
    вызовов = {"n": 0}

    def падает_на_второй(name: str, value: str) -> bytes:
        вызовов["n"] += 1
        if вызовов["n"] == 2:
            raise AccessError("сбой записи")
        return original(name, value)

    monkeypatch.setattr(secret_crypto, "encrypt", падает_на_второй)
    with pytest.raises(AccessError):
        store.replace_tokens(
            country="SI",
            tokens=новые,
            access_expires_at=НОВАЯ + timedelta(days=2),
            scope=None,
            now=НОВАЯ + timedelta(hours=1),
            expect_linked_at=вход.linked_at,
        )
    monkeypatch.setattr(secret_crypto, "encrypt", original)
    assert store.read_tokens("SI") == store.Tokens(ДОСТУП, ПРОДЛЕНИЕ), "пара заменилась наполовину"
    assert store.get_login("SI").refreshed_at == вход.refreshed_at  # type: ignore[union-attr]


def test_замена_пары_успех_и_устаревший_вход(база: str) -> None:
    вход = _вход()
    новые = store.Tokens("НОВЫЙ-доступ", "НОВОЕ-продление")
    store.replace_tokens(
        country="SI",
        tokens=новые,
        access_expires_at=НОВАЯ + timedelta(days=2),
        scope=None,
        now=НОВАЯ + timedelta(hours=1),
        expect_linked_at=вход.linked_at,
    )
    assert store.read_tokens("SI") == новые
    with pytest.raises(store.LoginSuperseded):
        store.replace_tokens(
            country="SI",
            tokens=store.Tokens("x", "y"),
            access_expires_at=НОВАЯ,
            scope=None,
            now=НОВАЯ,
            expect_linked_at=НОВАЯ - timedelta(days=1),
        )
    assert store.read_tokens("SI") == новые


def test_состояние_пишется_и_счёт_не_затирается(база: str) -> None:
    _вход()
    store.record_state("SI", "ok", None, now=НОВАЯ, units_total=12, units_open=11)
    store.record_state("SI", "expired", "refresh_rejected", now=НОВАЯ)
    вход = store.get_login("SI")
    assert вход is not None
    assert (вход.state, вход.units_total, вход.units_open) == ("expired", 12, 11)


def test_в_хранилище_нельзя_положить_чужое_имя(база: str) -> None:
    with psycopg.connect(база) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into vault.secrets (name, provider, ciphertext, last4, set_by) "
            "values ('dodois.access.russia', 'dodois', '\\x00', '****', 'x')"
        )


def test_роль_приложения_только_читает_входы(база: str, db_env: str) -> None:
    _вход()
    with psycopg.connect(db_env) as conn:
        assert conn.execute("select count(*) from dodois.logins").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update dodois.logins set state = 'failed'")


def test_имена_ключей_стран_строчные() -> None:
    assert rules.vault_names("SI") == ("dodois.access.si", "dodois.refresh.si")


def test_пробное_шифрование_отказывает_без_ключа_и_save_login_ничего_не_пишет(
    база: str, автор: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Сломанная копия: убрать `check_secrets_key()` из `save_login` — ссылка гасится до отказа.
    номер = _ссылка(база, автор)
    monkeypatch.delenv(secret_crypto.SECRETS_KEY_VAR)
    with pytest.raises(secret_crypto.SecretCryptoError):
        store.check_secrets_key()
    with pytest.raises(secret_crypto.SecretCryptoError):
        _вход(invite_id=номер)
    assert store.get_invite(номер).used_at is None  # type: ignore[union-attr]
    assert store.get_login("SI") is None


def test_вход_не_применён_ссылка_погашена_ключи_прежние(база: str, автор: str) -> None:
    # Сломанная копия: `reject_invite` не ставит `used_at` — ссылку можно пускать по кругу.
    _вход()
    номер = _ссылка(база, автор)
    store.reject_invite(номер, "SI", "Ana Novak", НОВАЯ)
    ссылка = store.get_invite(номер)
    assert ссылка is not None and ссылка.used_at == НОВАЯ
    assert (ссылка.result, ссылка.result_account) == ("not_applied", "Ana Novak")
    assert store.read_tokens("SI") == store.Tokens(ДОСТУП, ПРОДЛЕНИЕ), "прежняя пара тронута"
    with pytest.raises(store.InviteUnusable):
        store.reject_invite(номер, "SI", "Ana Novak", НОВАЯ)
    with pytest.raises(store.InviteUnusable):
        _вход(invite_id=номер)


def test_счёт_попыток_ссылок_свой_и_не_запирает_пароль_и_наоборот(база: str, автор: str) -> None:
    # Сломанная копия: `_link_key` возвращает `_address_key` — счёт общий, обе половины краснеют.
    for _n in range(25):
        web_throttle.note_link_failure(tenant="HQ", address="203.0.113.5")
        web_throttle.note_address_failure(tenant="HQ", address="198.51.100.9")
    assert web_throttle.link_address_verdict(tenant="HQ", address="203.0.113.5").locked
    assert not web_throttle.address_verdict(tenant="HQ", address="203.0.113.5").locked
    assert web_throttle.address_verdict(tenant="HQ", address="198.51.100.9").locked
    assert not web_throttle.link_address_verdict(tenant="HQ", address="198.51.100.9").locked
