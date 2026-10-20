"""Ключи сервисов в настоящей базе (D491, D576): нет открытого значения, закрытый список имён,
подмена шифртекста под чужое имя, порядок «база → окружение», права ролей, предел попыток.
"""

from __future__ import annotations

import base64
import os

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import secret_crypto, service_keys, web_throttle  # noqa: E402
from src.db.errors import AccessError  # noqa: E402
from src.domain import service_keys as registry  # noqa: E402

pytestmark = requires_db

ЗНАЧЕНИЕ = "sk-proj-Hh7Gg6Ff5Ee4Dd3Cc2Bb1Aa0-в-базе-только-шифртекст"
ИМЯ = "pointer.api_key"
ОКРУЖЕНИЕ = {"POINTER_API_KEY": "из-окружения-9999"}


@pytest.fixture
def хранилище(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(service_keys, "_cache", {})
    return pg_dsn


def test_в_базе_нет_открытого_значения(хранилище: str) -> None:
    # Сломанная копия: `save_many` кладёт value.encode() вместо шифртекста — тест падает.
    service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    with psycopg.connect(хранилище) as conn, conn.cursor() as cur:
        cur.execute("select ciphertext, row(s.*)::text from vault.secrets s")
        шифртекст, строка = cur.fetchone()
    assert ЗНАЧЕНИЕ.encode() not in bytes(шифртекст)
    assert ЗНАЧЕНИЕ not in строка and ЗНАЧЕНИЕ[:-4] not in строка, "открытый текст в строке"


def test_круг_запись_чтение_из_кэша_и_сброс(хранилище: str) -> None:
    записи = service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    запись = записи[ИМЯ]
    assert (запись.provider, запись.last4, запись.set_by) == ("pointer", ЗНАЧЕНИЕ[-4:], "director")
    assert запись.masked == "••••" + ЗНАЧЕНИЕ[-4:]
    assert service_keys.stored(ИМЯ) == ЗНАЧЕНИЕ
    service_keys.save_many({ИМЯ: "новое-0000"}, provider="pointer", by="other")
    assert service_keys.stored(ИМЯ) == "новое-0000", "кэш не сброшен записью"
    assert service_keys.status(ИМЯ).set_by == "other"  # type: ignore[union-attr]


def test_пара_ispring_пишется_и_убирается_вместе(хранилище: str) -> None:
    имена = {"ispring.client_id": "id-1234", "ispring.client_secret": "secret-5678"}
    service_keys.save_many(имена, provider="ispring", by="director")
    assert set(service_keys.statuses()) == set(имена)
    assert service_keys.clear_many(tuple(имена)) is True
    assert service_keys.statuses() == {}
    assert service_keys.clear_many(tuple(имена)) is False


def test_чужое_имя_отклоняется_кодом_и_базой(хранилище: str) -> None:
    # Сломанная копия: убрать `_known` — код пропускает имя, и тест падает на второй проверке
    # только если снять и `check` в 0084; обе стены проверяются по отдельности.
    with pytest.raises(AccessError):
        service_keys.save_many({"evil.name": ЗНАЧЕНИЕ}, provider="x", by="director")
    with pytest.raises(AccessError):
        service_keys.stored("evil.name")
    with psycopg.connect(хранилище) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "insert into vault.secrets (name, provider, ciphertext, last4, set_by) "
                "values ('evil.name', 'x', decode(repeat('00', 40), 'hex'), 'x', 'x')"
            )


def test_список_имён_в_базе_равен_реестру(хранилище: str) -> None:
    with psycopg.connect(хранилище) as conn, conn.cursor() as cur:
        cur.execute(
            "select pg_get_constraintdef(oid) from pg_constraint "
            "where conrelid = 'vault.secrets'::regclass and conname = 'secrets_name_check'"
        )
        определение = cur.fetchone()[0]
    for имя in registry.VAULT_NAMES:
        assert f"'{имя}'" in определение, f"{имя} есть в реестре, но не в check таблицы"
    assert определение.count("::text") == len(registry.VAULT_NAMES), "в check лишнее имя"


def test_шифртекст_одного_имени_не_открывается_под_другим(хранилище: str) -> None:
    # Сломанная копия: в `secret_crypto` убрать AAD — подложенное читается, тест падает.
    service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    with psycopg.connect(хранилище) as conn, conn.cursor() as cur:
        cur.execute(
            "update vault.secrets set name = 'ispring.client_secret' where name = %s", (ИМЯ,)
        )
    assert service_keys.stored("ispring.client_secret") is None, "подмена имени прочитана"
    assert service_keys.resolve("ispring", "client_secret", {}) is None


def test_порядок_база_потом_окружение(хранилище: str) -> None:
    # Сломанная копия: поменять местами ветки в `resolve` — падает первая проверка.
    assert service_keys.resolve("pointer", "api_key", ОКРУЖЕНИЕ) == "из-окружения-9999"
    assert service_keys.resolve("pointer", "api_key", {}) is None
    service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    assert service_keys.resolve("pointer", "api_key", ОКРУЖЕНИЕ) == ЗНАЧЕНИЕ
    service_keys.clear_many((ИМЯ,))
    assert service_keys.resolve("pointer", "api_key", ОКРУЖЕНИЕ) == "из-окружения-9999"


def test_неизвестное_поле_реестра_отклоняется(хранилище: str) -> None:
    with pytest.raises(AccessError):
        service_keys.resolve("pointer", "nope", {})


def test_другой_ключ_шифрования_значение_не_отдаёт_а_работа_не_падает(
    хранилище: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(service_keys, "_cache", {})
    assert service_keys.stored(ИМЯ) is None, "расшифровать нечем — наружу пусто, дальше окружение"


def test_без_ключа_шифрования_запись_отказана_и_таблица_пуста(
    хранилище: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(secret_crypto.SECRETS_KEY_VAR)
    with pytest.raises(secret_crypto.SecretCryptoError):
        service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    assert service_keys.statuses() == {}


def test_роль_приложения_читает_но_не_пишет(хранилище: str, db_env: str) -> None:
    service_keys.save_many({ИМЯ: ЗНАЧЕНИЕ}, provider="pointer", by="director")
    with psycopg.connect(db_env) as conn, conn.cursor() as cur:
        cur.execute("select count(*) from vault.secrets")
        assert cur.fetchone()[0] == 1
        for sql in (
            "delete from vault.secrets",
            "update vault.secrets set last4 = 'xxxx'",
            "insert into vault.secrets (name, provider, ciphertext, last4, set_by) "
            "values ('model_key', 'x', decode(repeat('00', 40), 'hex'), 'x', 'x')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(sql)
            conn.rollback()


def test_ключ_модели_остался_под_прежним_именем(хранилище: str) -> None:
    from src.db import model_key

    service_keys.save_many({"model_key": ЗНАЧЕНИЕ}, provider="openai", by="director")
    assert model_key.stored_key() == ЗНАЧЕНИЕ
    assert model_key.status().last4 == ЗНАЧЕНИЕ[-4:]  # type: ignore[union-attr]


# --- предел попыток на настоящей таблице ---------------------------------------------------


def test_предел_попыток_ключей_свой_и_с_обнулением(хранилище: str) -> None:
    порог = web_throttle.FAILURES_BEFORE_LOCK[web_throttle.SCOPE_LOGIN]
    итоги = [
        web_throttle.admit_service_key_action(tenant="rs", login="director") for _ in range(порог)
    ]
    assert all(и.admitted for и in итоги) and итоги[-1].verdict.locked
    assert not web_throttle.admit_service_key_action(tenant="rs", login="director").admitted
    # Вход под тем же логином запертым ключом экрана ключей не заперт.
    assert web_throttle.admit_attempt(tenant="rs", address="203.0.113.9", login="director").admitted
    web_throttle.note_service_key_ok(tenant="rs", login="director")
    assert web_throttle.admit_service_key_action(tenant="rs", login="director").admitted
