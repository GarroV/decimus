"""Вход ключом доступа с формы входа (D485): ключ — способ ВХОДА, а не вторая ступень.

Браузер с меткой «ключ тут есть» (`passkey.js`) на открытии `/login` сам просит у
устройства ключ без логина (discoverable: список допустимых пуст), сервер находит ключ по
номеру, номер ведёт к учётке, подпись открывает сессию. Пароль и Google остаются; кода при
этом входе нет.

**Вызов выдаётся без учётки** и привязан к случайной куке браузера (`decimus_passkey_login`,
2 минуты), снимается при первом же предъявлении. Проверки те же, что у остальных способов:
замороженную учётку `find_by_id` не отдаёт, попытки считает тот же ограничитель
(`web_throttle`), что и пароль, каждая попытка — в журнале входов (`method = passkey`).
Ответ один на все осечки: по различиям перебирающий узнавал бы, какие ключи заведены.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

from flask import Flask, current_app, jsonify, make_response, request
from werkzeug.wrappers import Response

from src.db import journals
from src.db import second_factor as store
from src.db.web_access import Account, OpenedSession, find_by_id, open_session
from src.db.web_throttle import admit_attempt, note_success
from src.domain.journal import (
    METHOD_PASSKEY,
    RESULT_OK,
    RESULT_PASSKEY_FAIL,
    RESULT_RATE_LIMITED,
)
from src.domain.second_factor import PASSKEY_LOGIN_TTL

from . import journal as web_journal
from . import webauthn_rp
from .config import Settings
from .origin import over_https, refuse_foreign_origin
from .remote import client_address
from .second_step import party_of

LOGIN_COOKIE = "decimus_passkey_login"
OPTIONS_PATH = "/login/passkey/options"
VERIFY_PATH = "/login/passkey/verify"
OPTIONS_ENDPOINT = "passkey_login_options"
VERIFY_ENDPOINT = "passkey_login_verify"
#: Адреса, открытые без сессии: их держит вызов за кукой браузера и подпись ключа.
ENDPOINTS = frozenset({OPTIONS_ENDPOINT, VERIFY_ENDPOINT})

#: Ключ счётчика попыток: по номеру ключа, который прислал браузер (адрес считается отдельно).
THROTTLE_PREFIX = "pk:"
#: Сколько знаков номера ключа идёт в счётчик: он приходит снаружи и не должен раздувать базу.
THROTTLE_ID_CHARS = 32


def install(
    app: Flask,
    conf: Settings,
    *,
    remember: Callable[[Response, OpenedSession], Response],
    stand: str,
) -> None:
    """Маршруты входа ключом. `remember` кладёт сессионную куку — тот же, что у пароля."""
    party = party_of(conf)
    max_age = int(PASSKEY_LOGIN_TTL.total_seconds())

    def _fail(*, status: int = 401) -> tuple[Response, int]:
        ответ = jsonify(error="failed")
        ответ.headers["Cache-Control"] = "no-store"
        return ответ, status

    @app.post(OPTIONS_PATH, endpoint=OPTIONS_ENDPOINT)
    def passkey_login_options() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        if party is None:
            return jsonify(error="off"), 400
        параметры, вызов = webauthn_rp.authentication_options(party, credential_ids=())
        токен = secrets.token_urlsafe(32)
        store.store_login_challenge(токен, challenge=вызов)
        ответ = current_app.response_class(параметры, mimetype="application/json")
        ответ.set_cookie(
            LOGIN_COOKIE,
            токен,
            max_age=max_age,
            httponly=True,
            samesite="Lax",
            secure=over_https(),
            path="/",
        )
        ответ.headers["Cache-Control"] = "no-store"
        return ответ

    @app.post(VERIFY_PATH, endpoint=VERIFY_ENDPOINT)
    def passkey_login_verify() -> Response | tuple[Response, int]:
        refuse_foreign_origin()
        if party is None:
            return jsonify(error="off"), 400
        сырое = request.get_data(as_text=True)
        откуда, браузер = web_journal.login_origin(conf)
        try:
            номер = webauthn_rp.credential_id_of(сырое)
        except webauthn_rp.PasskeyError:
            return _fail()
        ключ_счётчика = f"{THROTTLE_PREFIX}{номер.hex()[:THROTTLE_ID_CHARS]}"
        попытка = admit_attempt(
            tenant=stand,
            address=client_address(trusted_proxies=conf.trusted_proxies),
            login=ключ_счётчика,
        )
        if not попытка.admitted:
            journals.record_failed_login(
                method=METHOD_PASSKEY,
                ip=откуда,
                user_agent=браузер,
                result=RESULT_RATE_LIMITED,
            )
            ответ = jsonify(error="locked")
            ответ.headers["Retry-After"] = str(попытка.verdict.retry_after_seconds)
            return ответ, 429
        # Вызов снимается ВСЕГДА, до разбора ответа: попытка потрачена, повторить нельзя.
        вызов = store.take_login_challenge(request.cookies.get(LOGIN_COOKIE) or "")
        итог = _check(party, сырое, номер, вызов)
        if итог is None:
            journals.record_failed_login(
                method=METHOD_PASSKEY,
                ip=откуда,
                user_agent=браузер,
                result=RESULT_PASSKEY_FAIL,
            )
            return _fail()
        account = итог
        session = open_session(account, ip=откуда, user_agent=браузер, second_step=True)
        journals.record_login(
            method=METHOD_PASSKEY,
            result=RESULT_OK,
            user_id=account.id,
            ip=откуда,
            user_agent=браузер,
            session_id=session.session_id,
        )
        note_success(tenant=stand, login=ключ_счётчика)
        from .auth import after_login

        ведёт = after_login(request.args.get("next"))
        ответ = make_response(jsonify(ok=True, redirect=ведёт.headers["Location"]))
        ответ.delete_cookie(LOGIN_COOKIE, path="/")
        ответ.headers["Cache-Control"] = "no-store"
        return remember(ответ, session)

    def _check(
        rp: webauthn_rp.RelyingParty, сырое: str, номер: bytes, вызов: bytes | None
    ) -> Account | None:
        if вызов is None:
            return None
        найден = store.passkey_by_credential(номер)
        if найден is None:
            return None
        ключ, владелец = найден
        account = find_by_id(владелец)
        if account is None:
            return None
        try:
            итог = webauthn_rp.verify_authentication(
                rp,
                credential=сырое,
                challenge=вызов,
                public_key=ключ.public_key,
                sign_count=ключ.sign_count,
            )
        except webauthn_rp.PasskeyError:
            return None
        if not store.touch_passkey(
            ключ.id, old_count=ключ.sign_count, new_count=итог.new_sign_count
        ):
            return None
        return account
