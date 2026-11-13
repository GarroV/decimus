"""Отказы ключа в Chrome for Testing: настоящий JS и экран, без локального сервера.

Окно устройства заменено управляемым navigator.credentials: здесь проверяются
потерянная метка, отмена, сеть и истечение входа. Криптография и привязки браузера —
в test_web_second_factor_journeys.py на настоящей базе и в virtual_authenticator.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from conftest import chromium_executable
from web_harness import собрать

from src.db.second_factor import Passkey, Pending, Status
from src.db.web_access import Account
from src.web import second_step, webauthn_rp

playwright = pytest.importorskip("playwright.sync_api")
HOST = "https://admin.example"
STATIC = Path(__file__).resolve().parents[1] / "src/web/static"
USER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(scope="module")
def browser():  # type: ignore[no-untyped-def]
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chromium_executable(pw.chromium.executable_path), headless=True
        )
        yield browser
        browser.close()


@pytest.fixture
def screen(browser, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Настраиваемый браузерный отказ; реальные шаблон, стили и passkey.js."""
    contexts = []

    def open_screen(
        *,
        marker: bool = False,
        has_code: bool = False,
        error: str | None = None,
        options_status: int = 200,
        verify_status: int = 200,
        storage_denied: bool = False,
        supported: bool = True,
        width: int = 1440,
        registered: bool = True,
        other_origin: bool = False,
        keys_enabled: bool = True,
    ):
        app = собрать(
            tenant="HQ",
            webauthn_rp_id=("canonical.example" if other_origin else "admin.example")
            if keys_enabled
            else None,
            webauthn_origin=("https://canonical.example" if other_origin else HOST)
            if keys_enabled
            else None,
        )
        client = app.test_client()
        now = datetime.now(UTC)
        account = Account(id=USER, login="browser-test", tenant="HQ", role="admin")
        pending = Pending(
            "pending-id", USER, "password", "/settings", now + timedelta(minutes=5), 0
        )
        key = Passkey("key-id", b"test-key", b"public-key", 0, (), "Test", now, None)
        status = Status((key,) if registered else (), has_code, False, 0)
        monkeypatch.setattr(second_step, "find_by_id", lambda _: account)
        monkeypatch.setattr(second_step.store, "find_pending", lambda _: pending)
        monkeypatch.setattr(second_step.store, "status_of", lambda _: status)
        client.set_cookie(
            second_step.PENDING_COOKIE,
            app.extensions[second_step.SIGNER_KEY].dumps("browser-test-pending"),
        )
        context = browser.new_context(viewport={"width": width, "height": 900})
        contexts.append(context)
        context.add_init_script(
            """
            window.keyCalls = 0;
            window.createCalls = 0;
            const cfg = CONFIG;
            if (cfg.marker) localStorage.setItem('decimus.passkey.here', '1');
            if (cfg.storageDenied) Object.defineProperty(window, 'localStorage', {
                get() { throw new DOMException('blocked', 'SecurityError'); }
            });
            if (!cfg.supported) Object.defineProperty(window, 'PublicKeyCredential', {
                value: undefined
            });
            Object.defineProperty(navigator, 'credentials', { value: {
                get: async () => {
                    window.keyCalls++;
                    if (cfg.error) throw new DOMException('device declined', cfg.error);
                    const bytes = new Uint8Array([1, 2, 3]).buffer;
                    return { id: 'AQID', rawId: bytes, type: 'public-key',
                        response: {clientDataJSON: bytes, authenticatorData: bytes,
                            signature: bytes, userHandle: null} };
                },
                create: async () => {
                    window.createCalls++;
                    throw new DOMException('creation declined', cfg.error || 'NotAllowedError');
                }
            }});
        """.replace(
                "CONFIG",
                json.dumps(
                    {
                        "marker": marker,
                        "error": error,
                        "storageDenied": storage_denied,
                        "supported": supported,
                    }
                ),
            )
        )
        requests = []

        def respond(route):
            parsed = urlsplit(route.request.url)
            path = parsed.path
            if parsed.netloc != "admin.example":
                route.abort()
            elif path.startswith("/static/"):
                route.fulfill(path=str(STATIC / path.removeprefix("/static/")))
            elif path == second_step.STEP_PATH:
                response = client.get(path)
                route.fulfill(
                    status=response.status_code, body=response.data, content_type="text/html"
                )
            elif path.endswith(("/passkey/options", "/passkey/create-options")):
                create = path.endswith("/create-options")
                requests.append("create-options" if create else "options")
                if options_status == 0:
                    route.abort()
                    return
                party = webauthn_rp.RelyingParty("admin.example", HOST)
                if create:
                    options, _ = webauthn_rp.registration_options(
                        party, user_id=USER, login="browser-test", existing=()
                    )
                else:
                    options, _ = webauthn_rp.authentication_options(
                        party, credential_ids=(b"test-key",)
                    )
                body = (
                    options
                    if options_status == 200
                    else json.dumps(
                        {
                            "error": "expired" if options_status == 401 else "failed",
                            "login": "/login?second_step=expired",
                        }
                    )
                )
                route.fulfill(status=options_status, body=body, content_type="application/json")
            elif path.endswith("/passkey/verify"):
                requests.append("verify")
                route.fulfill(
                    status=verify_status,
                    json={
                        "ok": verify_status == 200,
                        "redirect": "/settings",
                        "error": "expired" if verify_status == 401 else "failed",
                        "login": "/login?second_step=expired",
                    },
                )
            elif path in ("/settings", "/login"):
                route.fulfill(body="<main>Destination</main>", content_type="text/html")
            else:
                route.abort()

        context.route("**/*", respond)
        page = context.new_page()
        page.goto(f"{HOST}{second_step.STEP_PATH}")
        return page, requests

    yield open_screen
    for context in contexts:
        context.close()


@pytest.mark.parametrize("marker", [True, False])
def test_saved_or_synced_key_can_sign_in_even_without_local_marker(screen, marker: bool) -> None:
    page, requests = screen(marker=marker)
    if not marker:
        assert page.evaluate("window.keyCalls") == 0
        page.locator("[data-passkey-button]").click()
    page.wait_for_url("**/settings")
    assert requests == ["options", "verify"]
    assert page.evaluate("window.createCalls") == 0


@pytest.mark.parametrize("error", ["NotAllowedError", "NotFoundError", "AbortError"])
def test_cancelled_automatic_key_attempt_explains_how_to_retry(screen, error: str) -> None:
    page, _ = screen(marker=True, error=error)
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    assert page.evaluate("window.keyCalls") == 1
    page.locator("[data-passkey-button]").click()
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    assert page.evaluate("window.keyCalls") == 2
    assert page.evaluate("window.createCalls") == 0


@pytest.mark.parametrize("marker", [True, False])
def test_expired_options_restart_the_password_step(screen, marker: bool) -> None:
    page, _ = screen(marker=marker, options_status=401)
    if not marker:
        page.locator("[data-passkey-button]").click()
    page.wait_for_url("**/login?second_step=expired", timeout=3000)


def test_expired_verification_restarts_password_step(screen) -> None:
    page, _ = screen(marker=True, verify_status=401)
    page.wait_for_url("**/login?second_step=expired")


@pytest.mark.parametrize("options_status", [0, 429, 500, 503])
def test_server_failure_does_not_leave_a_silent_key_screen(screen, options_status: int) -> None:
    page, requests = screen(marker=True, options_status=options_status)
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    assert requests == ["options"]
    assert page.evaluate("window.keyCalls") == 0


def test_storage_blocked_still_allows_manual_key_confirmation(screen) -> None:
    page, _ = screen(storage_denied=True)
    page.locator("[data-passkey-button]").click()
    page.wait_for_url("**/settings")


@pytest.mark.parametrize("width", [390, 1440])
def test_other_browser_keeps_app_code_available_without_creating_a_new_key(
    screen, width: int
) -> None:
    page, _ = screen(has_code=True, width=width)
    playwright.expect(page.locator('input[name="code"]')).to_be_visible()
    assert page.evaluate("window.keyCalls") == 0
    assert page.evaluate("window.createCalls") == 0
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_browser_without_webauthn_keeps_app_code_available(screen) -> None:
    page, _ = screen(has_code=True, supported=False)
    playwright.expect(page.locator("[data-passkey-button]")).to_be_disabled()
    playwright.expect(page.locator('[name="code"]')).to_be_visible()
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()


def test_no_code_screen_does_not_tell_user_to_enter_a_nonexistent_code(screen) -> None:
    page, _ = screen(error="NotAllowedError")
    page.locator("[data-passkey-button]").click()
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    assert "введите код" not in page.locator("[data-passkey-message]").inner_text()


@pytest.mark.parametrize("registered", [True, False])
def test_reloading_failed_step_does_not_repeat_the_automatic_prompt(
    screen, registered: bool
) -> None:
    page, requests = screen(marker=True, registered=registered, error="NotAllowedError")
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    page.reload()
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    action = "options" if registered else "create-options"
    assert requests == [action]
    expected = "Войти ключом доступа" if registered else "Подтвердить отпечатком"
    assert expected in page.locator("[data-passkey-message]").inner_text()
    page.locator("[data-passkey-button]").click()
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    assert requests == [action, action]


@pytest.mark.parametrize("error", ["NotAllowedError", "NotFoundError"])
def test_key_failure_keeps_the_portable_code_form_available(screen, error: str) -> None:
    page, _ = screen(marker=True, has_code=True, error=error)
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    playwright.expect(page.locator('[name="code"]')).to_be_visible()
    assert page.locator('[name="code"]').is_enabled()


@pytest.mark.parametrize("error", ["NotAllowedError", "InvalidStateError", "AbortError"])
def test_first_key_creation_failure_offers_retry_without_nonexistent_code(
    screen, error: str
) -> None:
    page, requests = screen(registered=False, error=error)
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    assert requests == ["create-options"]
    assert page.evaluate("window.createCalls") == 1
    assert "введите код" not in page.locator("[data-passkey-message]").inner_text()


def test_expired_first_key_creation_restarts_password_step(screen) -> None:
    page, _ = screen(registered=False, options_status=401)
    page.wait_for_url("**/login?second_step=expired")


def test_double_click_does_not_issue_two_key_challenges(screen) -> None:
    page, requests = screen()
    page.locator("[data-passkey-button]").evaluate("(button) => {button.click(); button.click();}")
    page.wait_for_url("**/settings")
    assert requests == ["options", "verify"]


def test_unsupported_browser_does_not_suggest_a_key_that_was_never_created(screen) -> None:
    page, _ = screen(registered=False, supported=False)
    playwright.expect(page.locator("[data-passkey-message]")).to_be_visible()
    text = page.locator("[data-passkey-message]").inner_text()
    assert "не поддерживает" in text
    assert "где сохранён ключ" not in text


@pytest.mark.parametrize("registered", [True, False])
def test_backup_address_explains_passkey_origin_before_opening_device_window(
    screen, registered: bool
) -> None:
    page, requests = screen(
        marker=True, registered=registered, has_code=registered, other_origin=True
    )
    playwright.expect(page.locator("[data-passkey-button]")).to_be_disabled()
    playwright.expect(page.locator("[data-passkey-origin-link]")).to_be_visible()
    assert (
        page.locator("[data-passkey-origin-link]").get_attribute("href")
        == "https://canonical.example"
    )
    assert requests == []
    if registered:
        playwright.expect(page.locator('[name="code"]')).to_be_visible()


@pytest.mark.parametrize("has_code", [True, False])
def test_disabled_passkeys_explain_only_available_recovery_methods(screen, has_code: bool) -> None:
    page, requests = screen(keys_enabled=False, has_code=has_code)
    assert requests == []
    if has_code:
        playwright.expect(page.locator('[name="code"]')).to_be_visible()
    else:
        playwright.expect(page.locator('[name="code"]')).to_have_count(0)
        assert "введите код" not in page.locator("main").inner_text().lower()
        assert "Обратитесь к главному админу" in page.locator("main").inner_text()
