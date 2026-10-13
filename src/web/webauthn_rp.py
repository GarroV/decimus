"""Ключи доступа (WebAuthn): тонкая обёртка над `webauthn` (duo-labs/py_webauthn, D463).

Криптографию и разбор ответов делает библиотека; здесь — только то, что решает
продукт, в одном месте:

* **домен и происхождение — из настроек** (`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGIN`), а не из
  заголовков запроса: заголовок подставляет любой, и проверка «ключ выпущен для нашего
  адреса» по нему ничего бы не значила;
* **проверка пользователя обязательна** (Touch ID или PIN, а не одно касание) и при
  регистрации, и при входе;
* **аттестация не нужна** (`none`): нам важно, что ключ принадлежит человеку, а не какой
  он фирмы;
* **откат счётчика подписей отвергается** (признак клона ключа) — библиотекой; ноль и
  ноль допустимы (синхронизируемые ключи iCloud/Google счётчик не ведут).

Любой отказ библиотеки — одна `PasskeyError`: подробности экрану не нужны, а по ним
перебирающий узнавал бы, на каком шаге остановился.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

#: Имя продукта в окне ключа доступа.
RP_NAME = "Decimus"

#: Сколько окно ключа ждёт человека, мс. Серверный срок вызова — `CHALLENGE_TTL`.
TIMEOUT_MS = 60_000


class PasskeyError(Exception):
    """Ключ доступа не принят: ответ не прошёл проверку (причина не раскрывается)."""


@dataclass(frozen=True)
class RelyingParty:
    """Кто мы для браузера: домен и происхождение из настроек."""

    rp_id: str
    origin: str


@dataclass(frozen=True)
class NewCredential:
    """Проверенная регистрация: что сохранить."""

    credential_id: bytes
    public_key: bytes
    sign_count: int
    transports: tuple[str, ...]


@dataclass(frozen=True)
class Assertion:
    """Проверенный вход ключом: новый счётчик подписей."""

    new_sign_count: int


def registration_options(
    party: RelyingParty, *, user_id: str, login: str, existing: tuple[bytes, ...]
) -> tuple[str, bytes]:
    """Параметры для `navigator.credentials.create` (JSON) и вызов, который надо запомнить.

    Уже зарегистрированные ключи названы в `excludeCredentials`: то же устройство второй
    раз не регистрируется.
    """
    параметры = generate_registration_options(
        rp_id=party.rp_id,
        rp_name=RP_NAME,
        user_id=uuid.UUID(user_id).bytes,
        user_name=login,
        user_display_name=login,
        timeout=TIMEOUT_MS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=i) for i in existing],
    )
    return options_to_json(параметры), параметры.challenge


def verify_registration(party: RelyingParty, *, credential: str, challenge: bytes) -> NewCredential:
    """Проверить ответ `credentials.create`. Любая осечка — `PasskeyError`."""
    try:
        проверено = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=party.rp_id,
            expected_origin=party.origin,
            require_user_verification=True,
        )
        return NewCredential(
            credential_id=проверено.credential_id,
            public_key=проверено.credential_public_key,
            sign_count=проверено.sign_count,
            transports=_transports_of(credential),
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as отказ:
        raise PasskeyError(type(отказ).__name__) from None


def authentication_options(
    party: RelyingParty, *, credential_ids: tuple[bytes, ...]
) -> tuple[str, bytes]:
    """Параметры для `navigator.credentials.get` (JSON) и вызов, который надо запомнить."""
    параметры = generate_authentication_options(
        rp_id=party.rp_id,
        timeout=TIMEOUT_MS,
        allow_credentials=[PublicKeyCredentialDescriptor(id=i) for i in credential_ids],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(параметры), параметры.challenge


def credential_id_of(credential: str) -> bytes:
    """Номер ключа из ответа браузера — чтобы найти его в базе до проверки подписи."""
    try:
        return base64url_to_bytes(str(json.loads(credential)["rawId"]))
    except (ValueError, KeyError, TypeError) as отказ:
        raise PasskeyError(type(отказ).__name__) from None


def verify_authentication(
    party: RelyingParty,
    *,
    credential: str,
    challenge: bytes,
    public_key: bytes,
    sign_count: int,
) -> Assertion:
    """Проверить ответ `credentials.get`: подпись, вызов, домен, происхождение, счётчик."""
    try:
        проверено = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=party.rp_id,
            expected_origin=party.origin,
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as отказ:
        raise PasskeyError(type(отказ).__name__) from None
    return Assertion(new_sign_count=проверено.new_sign_count)


def _transports_of(credential: str) -> tuple[str, ...]:
    """Способы связи, которые назвал браузер (usb, nfc, internal, hybrid…); мусор отбрасывается."""
    try:
        сырые = json.loads(credential).get("response", {}).get("transports") or []
    except (ValueError, AttributeError):
        return ()
    return tuple(t for t in сырые if isinstance(t, str) and t.isalnum() and len(t) <= 20)[:8]
