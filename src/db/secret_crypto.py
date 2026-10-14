"""Шифрование секретов, которые лежат в базе (D491): AES-256-GCM, ключ — вне базы.

Ключ шифрования — переменная окружения `SECRETS_KEY`: 32 случайных байта в base64
(`python3 -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"`).
В базу он не попадает никогда: получивший дамп базы шифртекст не открывает.

Формат значения: `nonce (12 байт) || шифртекст с тегом подлинности`. Имя секрета идёт
в связанные данные (AAD): шифртекст одного секрета нельзя подложить под другое имя.

Тексты отказов не содержат ни открытого значения, ни шифртекста, ни ключа шифрования.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import ConfigError

SECRETS_KEY_VAR = "SECRETS_KEY"
NONCE_BYTES = 12
KEY_BYTES = 32


class SecretCryptoError(ConfigError):
    """Ключ шифрования не задан или негоден, либо шифртекст не открылся."""


def _cipher(env: Mapping[str, str] | None) -> AESGCM:
    raw = ((os.environ if env is None else env).get(SECRETS_KEY_VAR) or "").strip()
    if not raw:
        raise SecretCryptoError(f"Не задан {SECRETS_KEY_VAR}: хранить секреты в базе нечем")
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SecretCryptoError(f"{SECRETS_KEY_VAR} не base64") from exc
    if len(key) != KEY_BYTES:
        raise SecretCryptoError(f"{SECRETS_KEY_VAR} должен быть {KEY_BYTES} байт в base64")
    return AESGCM(key)


def encrypt(name: str, value: str, env: Mapping[str, str] | None = None) -> bytes:
    """Зашифровать значение секрета `name`; каждый раз новый nonce."""
    nonce = os.urandom(NONCE_BYTES)
    return nonce + _cipher(env).encrypt(nonce, value.encode("utf-8"), name.encode("utf-8"))


def decrypt(name: str, blob: bytes, env: Mapping[str, str] | None = None) -> str:
    """Открыть шифртекст секрета `name`. Не открылся (чужой ключ, порча, подмена) — отказ."""
    cipher = _cipher(env)
    if len(blob) <= NONCE_BYTES:
        raise SecretCryptoError("Шифртекст секрета повреждён")
    try:
        return cipher.decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], name.encode("utf-8")).decode(
            "utf-8"
        )
    except (InvalidTag, UnicodeDecodeError) as exc:
        raise SecretCryptoError(
            f"Секрет «{name}» не открылся: {SECRETS_KEY_VAR} не тот, что при записи"
        ) from exc
