"""Ключи доступа: проверка регистрации и входа настоящим кодом `webauthn` (D463).

Без базы и без браузера: ключ — `tests/virtual_authenticator.py`. Каждое «сервер обязан
отвергнуть» — отдельный тест: проверка, не падающая на испорченном входе, проверкой не
является.
"""

from __future__ import annotations

import json
import uuid

import pytest
from virtual_authenticator import VirtualAuthenticator

from src.web import webauthn_rp as rp

СВОЙ = rp.RelyingParty(rp_id="decimus.example.test", origin="https://decimus.example.test")
ЧЕЛОВЕК = str(uuid.uuid4())


def _зарегистрирован(ключ: VirtualAuthenticator) -> rp.NewCredential:
    параметры, вызов = rp.registration_options(СВОЙ, user_id=ЧЕЛОВЕК, login="anna", existing=())
    ответ = ключ.create(параметры, origin=СВОЙ.origin)
    return rp.verify_registration(СВОЙ, credential=ответ, challenge=вызов)


def test_регистрация_принимает_настоящий_ответ() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    assert новое.credential_id == ключ.credential_id
    assert _годен(новое)


def _годен(новое: rp.NewCredential) -> bool:
    return bool(новое.public_key) and новое.transports == ("internal",)


def test_регистрация_с_чужого_происхождения_отвергается() -> None:
    ключ = VirtualAuthenticator()
    параметры, вызов = rp.registration_options(СВОЙ, user_id=ЧЕЛОВЕК, login="anna", existing=())
    ответ = ключ.create(параметры, origin="https://evil.example.test")
    with pytest.raises(rp.PasskeyError):
        rp.verify_registration(СВОЙ, credential=ответ, challenge=вызов)


def test_регистрация_с_чужим_доменом_отвергается() -> None:
    ключ = VirtualAuthenticator()
    параметры, вызов = rp.registration_options(СВОЙ, user_id=ЧЕЛОВЕК, login="anna", existing=())
    ответ = ключ.create(параметры, origin=СВОЙ.origin, rp_id="evil.example.test")
    with pytest.raises(rp.PasskeyError):
        rp.verify_registration(СВОЙ, credential=ответ, challenge=вызов)


def test_регистрация_с_чужим_вызовом_отвергается() -> None:
    ключ = VirtualAuthenticator()
    параметры, _ = rp.registration_options(СВОЙ, user_id=ЧЕЛОВЕК, login="anna", existing=())
    ответ = ключ.create(параметры, origin=СВОЙ.origin)
    with pytest.raises(rp.PasskeyError):
        rp.verify_registration(СВОЙ, credential=ответ, challenge=b"other-challenge-" * 3)


def test_регистрация_без_проверки_пользователя_отвергается() -> None:
    ключ = VirtualAuthenticator()
    параметры, вызов = rp.registration_options(СВОЙ, user_id=ЧЕЛОВЕК, login="anna", existing=())
    ответ = ключ.create(параметры, origin=СВОЙ.origin, user_verified=False)
    with pytest.raises(rp.PasskeyError):
        rp.verify_registration(СВОЙ, credential=ответ, challenge=вызов)


def test_регистрация_мусора_отвергается_без_падения() -> None:
    with pytest.raises(rp.PasskeyError):
        rp.verify_registration(СВОЙ, credential="{не json", challenge=b"x" * 32)
    with pytest.raises(rp.PasskeyError):
        rp.verify_registration(СВОЙ, credential="{}", challenge=b"x" * 32)


def _вход(ключ: VirtualAuthenticator, новое: rp.NewCredential, **порча: object) -> rp.Assertion:
    параметры, вызов = rp.authentication_options(СВОЙ, credential_ids=(новое.credential_id,))
    ответ = ключ.get(параметры, origin=порча.pop("origin", СВОЙ.origin), **порча)  # type: ignore[arg-type]
    return rp.verify_authentication(
        СВОЙ,
        credential=ответ,
        challenge=вызов,
        public_key=новое.public_key,
        sign_count=новое.sign_count,
    )


def test_вход_принимает_настоящую_подпись_и_растит_счётчик() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    итог = _вход(ключ, новое)
    assert итог.new_sign_count == 1


def test_вход_с_чужого_происхождения_отвергается() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    with pytest.raises(rp.PasskeyError):
        _вход(ключ, новое, origin="https://evil.example.test")


def test_вход_с_чужим_доменом_отвергается() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    with pytest.raises(rp.PasskeyError):
        _вход(ключ, новое, rp_id="evil.example.test")


def test_вход_без_проверки_пользователя_отвергается() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    with pytest.raises(rp.PasskeyError):
        _вход(ключ, новое, user_verified=False)


def test_вход_чужим_ключом_отвергается() -> None:
    ключ, чужой = VirtualAuthenticator(), VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    параметры, вызов = rp.authentication_options(СВОЙ, credential_ids=(новое.credential_id,))
    ответ = чужой.get(параметры, origin=СВОЙ.origin)
    чужой.credential_id = ключ.credential_id  # чужая подпись под нашим номером ключа
    with pytest.raises(rp.PasskeyError):
        rp.verify_authentication(
            СВОЙ, credential=ответ, challenge=вызов, public_key=новое.public_key, sign_count=0
        )


def test_откат_счётчика_подписей_отвергается() -> None:
    """Счётчик вернулся назад или не вырос — признак клона ключа."""
    ключ = VirtualAuthenticator(counter=5)
    новое = _зарегистрирован(ключ)
    параметры, вызов = rp.authentication_options(СВОЙ, credential_ids=(новое.credential_id,))
    ответ = ключ.get(параметры, origin=СВОЙ.origin, counter=3)
    with pytest.raises(rp.PasskeyError):
        rp.verify_authentication(
            СВОЙ, credential=ответ, challenge=вызов, public_key=новое.public_key, sign_count=10
        )
    ответ = ключ.get(параметры, origin=СВОЙ.origin, counter=10)
    with pytest.raises(rp.PasskeyError):
        rp.verify_authentication(
            СВОЙ, credential=ответ, challenge=вызов, public_key=новое.public_key, sign_count=10
        )


def test_нулевой_счётчик_синхронизируемого_ключа_допустим() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    параметры, вызов = rp.authentication_options(СВОЙ, credential_ids=(новое.credential_id,))
    ответ = ключ.get(параметры, origin=СВОЙ.origin, counter=0)
    итог = rp.verify_authentication(
        СВОЙ, credential=ответ, challenge=вызов, public_key=новое.public_key, sign_count=0
    )
    assert итог.new_sign_count == 0


def test_чужой_вызов_при_входе_отвергается() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    параметры, _ = rp.authentication_options(СВОЙ, credential_ids=(новое.credential_id,))
    ответ = ключ.get(параметры, origin=СВОЙ.origin)
    with pytest.raises(rp.PasskeyError):
        rp.verify_authentication(
            СВОЙ,
            credential=ответ,
            challenge=b"other-challenge-" * 3,
            public_key=новое.public_key,
            sign_count=0,
        )


def test_номер_ключа_достаётся_из_ответа() -> None:
    ключ = VirtualAuthenticator()
    новое = _зарегистрирован(ключ)
    параметры, _ = rp.authentication_options(СВОЙ, credential_ids=(новое.credential_id,))
    assert rp.credential_id_of(ключ.get(параметры, origin=СВОЙ.origin)) == ключ.credential_id
    with pytest.raises(rp.PasskeyError):
        rp.credential_id_of("не json")


def test_параметры_просят_встроенный_датчик_устройства() -> None:
    """Touch ID этого устройства, а не QR и телефон (D485): `hints` и платформенный ключ."""
    создание, _ = rp.registration_options(СВОЙ, user_id=ЧЕЛОВЕК, login="anna", existing=())
    вход, _ = rp.authentication_options(СВОЙ, credential_ids=(b"x" * 16,))

    assert json.loads(создание)["hints"] == ["client-device"]
    assert json.loads(создание)["authenticatorSelection"]["authenticatorAttachment"] == "platform"
    assert json.loads(вход)["hints"] == ["client-device"]
