"""Chrome + WebAuthn + настоящая база MUSPELHEIM, без локального HTTP-сервера.

Виртуальный аутентификатор Chrome создаёт и подписывает ключ настоящим WebAuthn.
Flask-клиент передаёт запросы в приложение; у каждого профиля своя серверная кука.
Проверяет регистрацию, повторный вход и ключ в новом профиле без localStorage.
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlsplit

import pyotp
import pytest
from conftest import chromium_executable, requires_db
from playwright.sync_api import expect, sync_playwright
from web_harness import собрать

from src.db import second_factor as sf
from src.db.web_access import authenticate, create_account
from src.domain.second_factor import totp_step_now
from src.web import second_step

pytestmark = requires_db
HOST = "https://admin.example"
PASSWORD = "browser-auth-test-not-a-real-account-password"


def test_chrome_key_survives_new_profile_without_local_storage(
    pg_dsn: str, db_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psycopg

    monkeypatch.setenv("DATABASE_ADMIN_URL", pg_dsn)
    monkeypatch.setattr(second_step, "REQUIRE_KEY_AT_LOGIN", True)
    create_account("browser-key-qa", tenant="HQ", password=PASSWORD, role="admin")
    account = authenticate("browser-key-qa", PASSWORD)
    assert account is not None
    app = собрать(tenant="HQ", webauthn_rp_id="admin.example", webauthn_origin=HOST)
    responses: list[tuple[str, int]] = []
    errors: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chromium_executable(pw.chromium.executable_path), headless=True
        )
        try:

            def profile(credentials=None):
                context = browser.new_context()
                client = app.test_client()

                def respond(route):
                    request = route.request
                    parsed = urlsplit(request.url)
                    if parsed.netloc != "admin.example":
                        route.abort()
                        return
                    headers = {
                        key: value
                        for key, value in request.headers.items()
                        if key.lower() not in ("host", "content-length", "cookie")
                    }
                    response = client.open(
                        parsed.path + (f"?{parsed.query}" if parsed.query else ""),
                        method=request.method,
                        data=request.post_data_buffer,
                        headers=headers,
                        base_url=HOST,
                    )
                    responses.append((parsed.path, response.status_code))
                    # Playwright перехватывает первый запрос цепочки 302; meta-навигация
                    # возвращает следующий GET в тот же Flask-клиент без локального сервера.
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
                                key: value
                                for key, value in response.headers.items()
                                if key.lower() not in ("content-length", "set-cookie")
                            },
                        )

                context.route("**/*", respond)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                cdp = context.new_cdp_session(page)
                cdp.send("WebAuthn.enable")
                authenticator = cdp.send(
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
                )["authenticatorId"]
                for credential in credentials or []:
                    cdp.send(
                        "WebAuthn.addCredential",
                        {
                            "authenticatorId": authenticator,
                            "credential": credential,
                        },
                    )
                return page, cdp, authenticator

            def login(page):
                page.goto(f"{HOST}/login?next=/settings")
                page.locator("#login").fill("browser-key-qa")
                page.locator("#password").fill(PASSWORD)
                page.locator(".login__form button[type=submit]").click()

            def logout(page):
                page.locator('form[action="/logout"]').evaluate("(form) => form.requestSubmit()")
                page.wait_for_url("**/welcome")

            # Первое создание ключа и открытие сессии (путь УК, D720).
            first, cdp, authenticator = profile()
            login(first)
            first.wait_for_url("**/settings")
            assert len(sf.status_of(account.id).passkeys) == 1
            assert first.evaluate("localStorage.getItem('decimus.passkey.here')") == "1"

            # Состояние прежнего партнёрского входа: ключ уже сохранён. Переносим
            # синтетическую учётку в партнёрское пространство и проверяем новые правила.
            with psycopg.connect(pg_dsn) as conn:
                conn.execute("insert into tenants(code) values ('browser-partner-qa')")
                conn.execute(
                    "update web_users set tenant_code='browser-partner-qa' where id=%s",
                    (account.id,),
                )

            # Тот же профиль подтверждает ключом; второй ключ не создаётся.
            logout(first)
            login(first)
            first.wait_for_url("**/settings")
            assert len(sf.status_of(account.id).passkeys) == 1
            assert sf.status_of(account.id).passkeys[0].last_used_at is not None
            exported = cdp.send("WebAuthn.getCredentials", {"authenticatorId": authenticator})

            # Новый профиль: метки нет, синхронизированный ключ есть. Кнопка get работает,
            # регистрировать второй ключ после одного пароля нельзя.
            second, _, _ = profile(exported["credentials"])
            login(second)
            second.wait_for_url("**/login/second-step")
            assert second.evaluate("localStorage.getItem('decimus.passkey.here')") is None
            before = len(responses)
            second.locator("[data-passkey-button]").click()
            second.wait_for_url("**/settings")
            assert ("/login/second-step/passkey/verify", 200) in responses[before:]
            assert not any("/passkey/create" in path for path, _ in responses[before:])
            assert len(sf.status_of(account.id).passkeys) == 1

            # Новый профиль БЕЗ ключа: пароль не позволяет зарегистрировать замену второму
            # фактору. При истечении полувхода кнопка корректно возвращает к паролю.
            third, _, _ = profile()
            login(third)
            third.wait_for_url("**/login/second-step")
            expect(third.locator('[name="code"]')).to_have_count(0)
            result = third.evaluate("""async () => {
                const res = await fetch('/login/second-step/passkey/create-options', {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
                });
                return res.status;
            }""")
            assert result == 403
            with psycopg.connect(pg_dsn) as conn:
                conn.execute(
                    "update web_second_steps set expires_at=now()-interval '1 second' "
                    "where user_id=%s and consumed_at is null",
                    (account.id,),
                )
            third.locator("[data-passkey-button]").click()
            third.wait_for_url("**/login?second_step=expired")

            # Партнёр подключает переносимый код из уже доказанной сессии. Новый
            # профиль без какого-либо ключа входит этим кодом, а ключ не дублируется.
            second.goto(f"{HOST}/settings/security")
            second.locator('form[action*="/totp/start"] button').click()
            setup = sf.totp_of(account.id)
            assert setup is not None
            second.locator('form[action*="/totp/confirm"] [name="code"]').fill(
                pyotp.TOTP(setup.secret).at((totp_step_now() - 1) * 30)
            )
            second.locator('form[action*="/totp/confirm"] button').click()
            expect(second.locator(".sqr")).to_have_count(0)
            fourth, _, _ = profile()
            login(fourth)
            fourth.wait_for_url("**/login/second-step")
            fourth.locator('form[action*="/second-step/code"] [name="code"]').fill(
                pyotp.TOTP(setup.secret).now()
            )
            fourth.locator('form[action*="/second-step/code"] button').click()
            fourth.wait_for_url("**/settings")
            assert len(sf.status_of(account.id).passkeys) == 1
            assert not errors, errors
        finally:
            browser.close()
