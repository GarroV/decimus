"""Шифрование секретов в базе (D491): круг, отказы, нет открытого текста в шифртексте.

Ядро безопасности: каждая проверка прогонялась на сломанной копии (см. заголовок каждого
теста, что именно ломалось).
"""

from __future__ import annotations

import base64
import os

import pytest

from src.db import secret_crypto
from src.db.errors import ConfigError

КЛЮЧ = "sk-proj-Aa1Bb2Cc3Dd4Ee5Ff6-секрет-9876"


def _env() -> dict[str, str]:
    return {secret_crypto.SECRETS_KEY_VAR: base64.b64encode(os.urandom(32)).decode()}


def test_круг_шифрование_и_обратно() -> None:
    env = _env()
    блоб = secret_crypto.encrypt("model_key", КЛЮЧ, env)
    assert secret_crypto.decrypt("model_key", блоб, env) == КЛЮЧ


def test_в_шифртексте_нет_открытого_значения() -> None:
    # Сломанная копия: `encrypt` возвращает value.encode() — проверка падает.
    блоб = secret_crypto.encrypt("model_key", КЛЮЧ, _env())
    assert КЛЮЧ.encode() not in блоб
    assert КЛЮЧ[-12:].encode() not in блоб
    assert len(блоб) > len(КЛЮЧ.encode()) + secret_crypto.NONCE_BYTES


def test_каждый_раз_новый_nonce() -> None:
    env = _env()
    assert secret_crypto.encrypt("model_key", КЛЮЧ, env) != secret_crypto.encrypt(
        "model_key", КЛЮЧ, env
    )


def test_чужой_ключ_шифрования_не_открывает() -> None:
    блоб = secret_crypto.encrypt("model_key", КЛЮЧ, _env())
    with pytest.raises(secret_crypto.SecretCryptoError) as err:
        secret_crypto.decrypt("model_key", блоб, _env())
    assert КЛЮЧ not in str(err.value)


def test_шифртекст_не_подложить_под_другое_имя() -> None:
    env = _env()
    блоб = secret_crypto.encrypt("model_key", КЛЮЧ, env)
    with pytest.raises(secret_crypto.SecretCryptoError):
        secret_crypto.decrypt("other", блоб, env)


def test_порченный_шифртекст_не_открывается() -> None:
    env = _env()
    блоб = bytearray(secret_crypto.encrypt("model_key", КЛЮЧ, env))
    блоб[-1] ^= 1
    with pytest.raises(secret_crypto.SecretCryptoError):
        secret_crypto.decrypt("model_key", bytes(блоб), env)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {secret_crypto.SECRETS_KEY_VAR: ""},
        {secret_crypto.SECRETS_KEY_VAR: "не-base64!"},
        {secret_crypto.SECRETS_KEY_VAR: base64.b64encode("коротко".encode()).decode()},
    ],
)
def test_нет_или_негоден_ключ_шифрования_отказ_а_не_молчание(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        secret_crypto.encrypt("model_key", КЛЮЧ, env)
