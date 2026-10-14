"""Ключ модели в настоящей базе (D491): нет открытого значения, права ролей, круг записи."""

from __future__ import annotations

import base64
import os

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import model_key, secret_crypto  # noqa: E402

pytestmark = requires_db

КЛЮЧ = "sk-proj-Hh7Gg6Ff5Ee4Dd3Cc2Bb1Aa0-в-базе-только-шифртекст"


@pytest.fixture
def хранилище(pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(model_key, "_cache", None)
    return pg_dsn


def test_в_базе_нет_открытого_значения(хранилище: str) -> None:
    # Сломанная копия: `save` кладёт value.encode() вместо шифртекста — тест падает.
    model_key.save(КЛЮЧ, by="director")
    with psycopg.connect(хранилище) as conn, conn.cursor() as cur:
        cur.execute("select ciphertext, row(s.*)::text from vault.secrets s")
        шифртекст, строка = cur.fetchone()
    assert КЛЮЧ.encode() not in bytes(шифртекст)
    assert КЛЮЧ not in строка and КЛЮЧ[:-4] not in строка, "открытый текст в строке таблицы"


def test_круг_запись_чтение_из_кэша_и_сброс(хранилище: str) -> None:
    запись = model_key.save(КЛЮЧ, by="director")
    assert (запись.provider, запись.last4, запись.set_by) == ("openai", КЛЮЧ[-4:], "director")
    assert запись.masked == "••••" + КЛЮЧ[-4:]
    assert model_key.stored_key() == КЛЮЧ
    # Замена: новое значение видно сразу в этом процессе (кэш сброшен записью).
    model_key.save("sk-новый-0000", by="other")
    assert model_key.stored_key() == "sk-новый-0000"
    assert model_key.status().set_by == "other"  # type: ignore[union-attr]


def test_удаление_возвращает_пусто(хранилище: str) -> None:
    model_key.save(КЛЮЧ, by="director")
    assert model_key.clear() is True
    assert model_key.stored_key() is None and model_key.status() is None
    assert model_key.clear() is False


def test_другой_ключ_шифрования_ключ_не_отдаёт_а_разбор_не_падает(
    хранилище: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_key.save(КЛЮЧ, by="director")
    monkeypatch.setenv(secret_crypto.SECRETS_KEY_VAR, base64.b64encode(os.urandom(32)).decode())
    monkeypatch.setattr(model_key, "_cache", None)
    assert model_key.stored_key() is None, "расшифровать нечем — наружу пусто, дальше окружение"


def test_без_ключа_шифрования_запись_отказана_и_таблица_пуста(
    хранилище: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(secret_crypto.SECRETS_KEY_VAR)
    with pytest.raises(secret_crypto.SecretCryptoError):
        model_key.save(КЛЮЧ, by="director")
    assert model_key.status() is None


def test_роль_приложения_читает_но_не_пишет(хранилище: str, db_env: str) -> None:
    model_key.save(КЛЮЧ, by="director")
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
