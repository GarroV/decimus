"""Виртуальный ключ доступа для тестов второй ступени (D463).

Делает то, что делает устройство человека: по параметрам сервера создаёт ключ и подписывает
вход. Без браузера и без базы — только `cryptography` и `cbor2`, поэтому проверки
сервера (домен, происхождение, вызов, счётчик) идут настоящим кодом библиотеки `webauthn`.

Всё, что тест хочет испортить, — параметры метода (`origin`, `rp_id`, `counter`, `uv`):
сервер обязан отвергнуть каждую порчу.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class VirtualAuthenticator:
    """Один ключ доступа: пара ES256, номер ключа, счётчик подписей."""

    def __init__(self, counter: int = 0) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.counter = counter

    def _cose_public_key(self) -> bytes:
        числа = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,
                3: -7,
                -1: 1,
                -2: числа.x.to_bytes(32, "big"),
                -3: числа.y.to_bytes(32, "big"),
            }
        )

    def create(
        self,
        options_json: str,
        *,
        origin: str,
        rp_id: str | None = None,
        user_verified: bool = True,
        challenge: bytes | None = None,
    ) -> str:
        """Ответ `navigator.credentials.create` на параметры сервера."""
        параметры = json.loads(options_json)
        вызов = challenge if challenge is not None else unb64(параметры["challenge"])
        домен = rp_id or параметры["rp"]["id"]
        client_data = json.dumps(
            {"type": "webauthn.create", "challenge": b64(вызов), "origin": origin}
        ).encode()
        флаги = FLAG_UP | FLAG_AT | (FLAG_UV if user_verified else 0)
        данные = (
            hashlib.sha256(домен.encode()).digest()
            + bytes([флаги])
            + self.counter.to_bytes(4, "big")
            + bytes(16)
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + self._cose_public_key()
        )
        аттестация = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": данные})
        return json.dumps(
            {
                "id": b64(self.credential_id),
                "rawId": b64(self.credential_id),
                "type": "public-key",
                "response": {
                    "clientDataJSON": b64(client_data),
                    "attestationObject": b64(аттестация),
                    "transports": ["internal"],
                },
                "clientExtensionResults": {},
                "authenticatorAttachment": "platform",
            }
        )

    def get(
        self,
        options_json: str,
        *,
        origin: str,
        rp_id: str | None = None,
        counter: int | None = None,
        user_verified: bool = True,
        challenge: bytes | None = None,
    ) -> str:
        """Ответ `navigator.credentials.get`: подпись над данными и хешем clientData."""
        параметры = json.loads(options_json)
        вызов = challenge if challenge is not None else unb64(параметры["challenge"])
        домен = rp_id or параметры["rpId"]
        if counter is None:
            self.counter += 1
        else:
            self.counter = counter
        client_data = json.dumps(
            {"type": "webauthn.get", "challenge": b64(вызов), "origin": origin}
        ).encode()
        флаги = FLAG_UP | (FLAG_UV if user_verified else 0)
        данные = (
            hashlib.sha256(домен.encode()).digest()
            + bytes([флаги])
            + self.counter.to_bytes(4, "big")
        )
        подпись = self.key.sign(
            данные + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        ответ: dict[str, Any] = {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(данные),
                "signature": b64(подпись),
            },
            "clientExtensionResults": {},
        }
        return json.dumps(ответ)
