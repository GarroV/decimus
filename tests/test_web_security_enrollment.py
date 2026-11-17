"""Регистрация ключа требует существующий фактор, кроме первого подключения (D485).

Настоящие Flask, Postgres и виртуальный WebAuthn: первая ступень после Google
не превращается в доказанную сессию через регистрацию чужого нового ключа.
"""


# ruff: noqa: F811 -- imported pytest fixture is injected by name

from __future__ import annotations

import hashlib
import json
from html import escape
from urllib.parse import urlsplit

import pytest
from conftest import chromium_executable, requires_db
from itsdangerous import URLSafeTimedSerializer
from test_web_second_factor_journeys import (  # noqa: F401 -- pytest fixture injection
    HDR,
    ORIGIN,
    SECURITY,
    Стенд,
    _код,
    _подключить_ключ,
    стенд,
)
from virtual_authenticator import VirtualAuthenticator

from src.db import second_factor as sf
from src.db.web_access import authenticate, open_session
from src.domain.journal import METHOD_GOOGLE
from src.domain.second_factor import totp_step_now
from src.web import auth, second_step

pytestmark = requires_db


def _google_session(stand: Стенд, monkeypatch: pytest.MonkeyPatch) -> str:
    """УК control вправе войти Google без второй ступени, хотя TOTP уже подключён."""
    from test_web_second_factor_journeys import ПАРОЛЬ

    monkeypatch.setattr("src.web.login_alert.notify_login", lambda *a, **k: None)
    uid = stand.завести("key-enrollment-control", "control")
    stand.с_приложением("key-enrollment-control")
    account = authenticate("key-enrollment-control", ПАРОЛЬ)
    assert account is not None
    assert not second_step.step_required(METHOD_GOOGLE, account)
    session = open_session(account, step_waived=True)
    conf = stand.client.application.extensions["decimus_conf"]
    signer = URLSafeTimedSerializer(
        conf.secret_key, salt=auth.COOKIE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )
    stand.client.set_cookie(auth.COOKIE_NAME, signer.dumps(session.token))
    return uid


def test_google_session_cannot_add_key_without_existing_factor_proof(
    стенд: Стенд, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = _google_session(стенд, monkeypatch)
    # Даже корректная регистрационная подпись и сохранённый вызов не заменяют
    # доказательство уже настроенного фактора. Проверяем register отдельно от options.
    from src.web import webauthn_rp
    from src.web.second_step import party_of

    conf = стенд.client.application.extensions["decimus_conf"]
    party = party_of(conf)
    assert party is not None
    options, challenge = webauthn_rp.registration_options(
        party, user_id=uid, login="key-enrollment-control", existing=()
    )
    cookie = стенд.client.get_cookie(auth.COOKIE_NAME)
    assert cookie is not None
    signer = URLSafeTimedSerializer(
        conf.secret_key, salt=auth.COOKIE_SALT, signer_kwargs={"digest_method": hashlib.sha256}
    )
    sf.store_challenge(
        signer.loads(cookie.value), purpose=sf.PURPOSE_REGISTER, user_id=uid, challenge=challenge
    )
    credential = json.loads(VirtualAuthenticator().create(options, origin=ORIGIN))
    options_response = стенд.client.post(f"{SECURITY}/passkey/options", headers=HDR)
    register_response = стенд.client.post(
        f"{SECURITY}/passkey/register", json={"credential": credential}, headers=HDR
    )
    assert (options_response.status_code, register_response.status_code) == (403, 403)
    assert sf.status_of(uid).passkeys == ()
    assert sf.status_of(uid).totp_confirmed
    assert стенд.client.post(f"{SECURITY}/totp/remove", headers=HDR).status_code == 403
    assert sf.status_of(uid).totp_confirmed


def test_proved_google_session_can_add_several_keys(
    стенд: Стенд, monkeypatch: pytest.MonkeyPatch
) -> None:
    uid = _google_session(стенд, monkeypatch)
    setup = sf.totp_of(uid)
    assert setup is not None
    proof = стенд.client.post(
        f"{SECURITY}/prove", data={"code": _код(setup.secret, totp_step_now())}, headers=HDR
    )
    assert proof.status_code == 302 and "proved=1" in proof.location
    _подключить_ключ(стенд, стенд.client, VirtualAuthenticator())
    _подключить_ключ(стенд, стенд.client, VirtualAuthenticator())
    assert len(sf.status_of(uid).passkeys) == 2


def test_first_setup_can_continue_adding_keys_without_gaining_removal_rights(стенд: Стенд) -> None:
    стенд.вход_паролем("dev")
    _подключить_ключ(стенд, стенд.client, VirtualAuthenticator())
    _подключить_ключ(стенд, стенд.client, VirtualAuthenticator())
    keys = sf.status_of(стенд.ид["dev"]).passkeys
    assert len(keys) == 2
    assert (
        стенд.client.post(f"{SECURITY}/passkey/{keys[0].id}/delete", headers=HDR).status_code == 403
    )
    assert len(sf.status_of(стенд.ид["dev"]).passkeys) == 2


def test_factor_change_during_registration_is_checked_inside_write_transaction(
    стенд: Стенд, monkeypatch: pytest.MonkeyPatch
) -> None:
    стенд.вход_паролем("dev")
    uid = стенд.ид["dev"]
    options = стенд.client.post(f"{SECURITY}/passkey/options", headers=HDR)
    assert options.status_code == 200
    credential = json.loads(
        VirtualAuthenticator().create(options.get_data(as_text=True), origin=ORIGIN)
    )
    original = sf.add_passkey

    def factor_appears(*args, **kwargs):
        # Состояние поменялось после всех предварительных чтений, но перед
        # транзакцией записи. Фактор старше входа, auth.current_account уже устарел.
        стенд.с_приложением("dev")
        стенд.sql(
            "update web_totp set confirmed_at = now() - interval '1 hour' where user_id = %s", uid
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(sf, "add_passkey", factor_appears)
    response = стенд.client.post(
        f"{SECURITY}/passkey/register", json={"credential": credential}, headers=HDR
    )
    assert response.status_code == 403
    assert sf.status_of(uid).passkeys == ()
    assert sf.status_of(uid).totp_confirmed


def test_chrome_auto_enrollment_refusal_leads_to_existing_factor_proof(
    стенд: Стенд, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Настоящий JS: отказ автосохранения → подтверждение TOTP → создание ключа Chrome."""
    from playwright.sync_api import expect, sync_playwright

    uid = _google_session(стенд, monkeypatch)
    # Flask-набор по умолчанию ходит на localhost; Chrome проверяет настоящий
    # origin WebAuthn, поэтому его синтетическая сессия принадлежит этому хосту.
    cookie = стенд.client.get_cookie(auth.COOKIE_NAME)
    assert cookie is not None
    client = стенд.новый_браузер()
    client.set_cookie(auth.COOKIE_NAME, cookie.value, domain="admin.example")
    responses: list[tuple[str, int]] = []
    errors: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chromium_executable(pw.chromium.executable_path), headless=True
        )
        try:
            context = browser.new_context()

            def respond(route):
                req = route.request
                parsed = urlsplit(req.url)
                if parsed.netloc != "admin.example":
                    route.abort()
                    return
                response = client.open(
                    parsed.path + (f"?{parsed.query}" if parsed.query else ""),
                    method=req.method,
                    data=req.post_data_buffer,
                    headers={
                        k: v
                        for k, v in req.headers.items()
                        if k.lower() not in ("host", "content-length", "cookie")
                    },
                    base_url=ORIGIN,
                )
                responses.append((parsed.path, response.status_code))
                if response.status_code in (301, 302, 303):
                    route.fulfill(
                        content_type="text/html",
                        body='<meta http-equiv="refresh" content="0;url='
                        + escape(response.location, quote=True)
                        + '">',
                    )
                else:
                    route.fulfill(
                        status=response.status_code,
                        body=response.data,
                        headers={
                            k: v
                            for k, v in response.headers.items()
                            if k.lower() not in ("content-length", "set-cookie")
                        },
                    )

            context.route("**/*", respond)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            cdp = context.new_cdp_session(page)
            cdp.send("WebAuthn.enable")
            cdp.send(
                "WebAuthn.addVirtualAuthenticator",
                {
                    "options": {
                        "protocol": "ctap2",
                        "transport": "internal",
                        "hasResidentKey": True,
                        "hasUserVerification": True,
                        "isUserVerified": True,
                        "automaticPresenceSimulation": True,
                    }
                },
            )
            page.goto(f"{ORIGIN}/settings")
            expect(page.locator("[data-passkey-here]")).to_be_visible()
            assert (f"{SECURITY}/passkey/options", 403) in responses
            assert sf.status_of(uid).passkeys == ()
            page.locator("[data-passkey-here]").click()
            page.wait_for_url(lambda url: urlsplit(url).path == SECURITY)
            expect(page.locator("#prove")).to_be_visible()
            setup = sf.totp_of(uid)
            assert setup is not None
            page.locator('#prove [name="code"]').fill(_код(setup.secret, totp_step_now()))
            page.locator('#prove form button[type="submit"]').click()
            page.wait_for_url("**/security?proved=1")
            with page.expect_response(
                lambda response: (
                    urlsplit(response.url).path == f"{SECURITY}/passkey/register"
                    and response.status == 200
                )
            ):
                page.goto(f"{ORIGIN}/settings")
            expect(page.locator("[data-passkey-here]")).to_be_hidden()
            assert (f"{SECURITY}/passkey/register", 200) in responses
            assert len(sf.status_of(uid).passkeys) == 1
            assert not errors
        finally:
            browser.close()


def test_first_key_at_login_rechecks_no_factor_inside_write(
    стенд: Стенд, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Первое подключение на входе не выдаёт MFA-сессию при сменившемся факторе."""
    monkeypatch.setattr(second_step, "REQUIRE_KEY_AT_LOGIN", True)
    стенд.вход_паролем("anna")
    path = second_step.STEP_PATH
    options = стенд.client.post(f"{path}/passkey/create-options", headers=HDR)
    assert options.status_code == 200
    credential = json.loads(
        VirtualAuthenticator().create(options.get_data(as_text=True), origin=ORIGIN)
    )
    original = sf.add_passkey

    def factor_appears(*args, **kwargs):
        стенд.с_приложением("anna")
        return original(*args, **kwargs)

    monkeypatch.setattr(sf, "add_passkey", factor_appears)
    response = стенд.client.post(
        f"{path}/passkey/create", json={"credential": credential}, headers=HDR
    )
    assert response.status_code == 403
    assert sf.status_of(стенд.ид["anna"]).passkeys == ()
    assert sf.status_of(стенд.ид["anna"]).totp_confirmed
    assert стенд.client.get_cookie(auth.COOKIE_NAME) is None
