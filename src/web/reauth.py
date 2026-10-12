"""Свежий вход для действий, создающих долгоживущий доступ (аудит безопасности 12.10).

Одной украденной сессией нельзя выпустить себе 30-дневный токен MCP, привязать
свой Telegram, привязать или снять почту Google и разрешить подключение Claude:
эти права пережили бы выход и смену пароля. Поэтому такие действия требуют
входа в ЭТОЙ сессии не старше `MAX_AGE`; иначе — страница «Подтвердите вход»
(`/settings/confirm`) тем же способом, каким учётка входит: паролем или, у
учётки с почтой Google при включённом входе Google (D450), через Google.

Подтверждение не продлевает старую сессию, а заменяет её новой: прежняя
закрывается, новая открывается с текущим временем. Так «когда вошли» остаётся
одним полем базы (`web_sessions.issued_at`), а не вторым, которое надо держать
в согласии с первым.

После подтверждения человек возвращается туда, откуда его попросили: в нужный
раздел «Настроек» (там он нажимает кнопку ещё раз — POST повторно не
отправляется) или на страницу согласия Claude.

Попытки пароля считаются тем же счётчиком, что у входа: иначе подтверждение
было бы вторым входом для подбора.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, make_response, redirect, render_template, request, url_for
from werkzeug.wrappers import Response

from src.db.web_throttle import admit_attempt, note_success
from src.domain.tenants import HQ_TENANT, canonical_tenant

from .google_auth import GoogleIdentity, hq_domain_ok
from .google_link import nonce_for
from .origin import refuse_foreign_origin
from .remote import client_address

#: Сколько вход считается свежим для действий, создающих долгоживущий доступ.
MAX_AGE = timedelta(minutes=15)

CONFIRM_PATH = "/settings/confirm"
CONFIRM_GOOGLE_PATH = "/settings/confirm/google"
CONFIRM_ENDPOINT = "reauth_confirm"

#: Вид метки в куке захода Google: подтверждение входа.
REAUTH_KIND = "reauth"

#: Куда можно вернуть после подтверждения: «Настройки» и согласие OAuth.
_BACK_PREFIXES = ("/settings#", "/settings?", "/oauth/authorize?")


def is_fresh(account: object, *, now: datetime | None = None) -> bool:
    """Сессия открыта не раньше `MAX_AGE` назад. Неизвестно когда — не свежая."""
    когда = getattr(account, "signed_in_at", None)
    if not isinstance(когда, datetime):
        return False
    сейчас = now or datetime.now(UTC)
    return сейчас - когда <= MAX_AGE


def safe_back(raw: str | None) -> str:
    """Путь возврата после подтверждения — только свои страницы; иначе «Настройки»."""
    if raw == "/settings":
        return raw
    if (
        raw
        and raw.startswith(_BACK_PREFIXES)
        and "\\" not in raw
        and all(знак.isprintable() for знак in raw)
        and not urlsplit(raw).netloc
        and not urlsplit(raw).scheme
    ):
        return raw
    return "/settings"


def require_fresh(back: str) -> Response | None:
    """`None` — вход свежий, действие можно делать; иначе — увод на подтверждение."""
    from . import auth

    if is_fresh(auth.current_account()):
        return None
    return ask_confirm(back)


def ask_confirm(back: str) -> Response:
    """Увести на «Подтвердите вход» с возвратом на `back`."""
    return redirect(url_for(CONFIRM_ENDPOINT, next=back))


def uses_google(account: object, google_enabled: bool) -> bool:
    """Учётка подтверждает вход через Google: с почтой паролем не входят (D450)."""
    return google_enabled and bool(getattr(account, "email", None))


def google_confirms(
    account: Any, identity: GoogleIdentity, *, state: str, hq_domains: frozenset[str]
) -> bool:
    """Google подтвердил ТУ ЖЕ учётку: её почта, подтверждена, этот заход, домен УК."""
    if not identity.email_verified or not account.email:
        return False
    if not identity.nonce or not hmac.compare_digest(
        identity.nonce.encode(), nonce_for(state).encode()
    ):
        return False
    if identity.email != str(account.email).strip().lower():
        return False
    if canonical_tenant(account.tenant) == HQ_TENANT and not hq_domain_ok(identity, hq_domains):
        return False
    return True


def install(
    app: Flask,
    *,
    stand: str,
    trusted_proxies: int,
    google_enabled: bool,
    rotate: Callable[[Any, str], Response],
    begin_google: Callable[[str], Response],
    verify: Callable[[str, str], Any],
) -> None:
    """Страница подтверждения входа.

    `rotate(account, back)` меняет сессию на свежую, `begin_google(back)` уводит
    к Google, `verify(login, password)` — сверка пароля той же дверью, что у входа.
    """

    def _page(back: str, *, failed: bool = False, locked: int | None = None) -> str:
        from . import auth

        return render_template(
            "settings/confirm.html",
            back=back,
            via_google=uses_google(auth.current_account(), google_enabled),
            failed=failed,
            locked_minutes=locked,
        )

    @app.get(CONFIRM_PATH, endpoint=CONFIRM_ENDPOINT)
    def reauth_confirm() -> str:
        return _page(safe_back(request.args.get("next")), failed=request.args.get("failed") == "1")

    @app.post(CONFIRM_PATH)
    def reauth_confirm_password() -> Response | tuple[str, int]:
        from . import auth

        refuse_foreign_origin()
        back = safe_back(request.form.get("next"))
        account = auth.current_account()
        if account is None:
            raise RuntimeError("подтверждение без вошедшего: маршрут прошёл мимо заслона")
        if uses_google(account, google_enabled):
            return _page(back), 403
        адрес = client_address(trusted_proxies=trusted_proxies)
        попытка = admit_attempt(tenant=stand, address=адрес, login=account.login)
        if not попытка.admitted:
            ответ = make_response(_page(back, locked=попытка.verdict.retry_after_minutes), 429)
            ответ.headers["Retry-After"] = str(попытка.verdict.retry_after_seconds)
            return ответ
        сверено = verify(account.login, request.form.get("password") or "")
        if сверено is None or str(сверено.id) != str(account.id):
            return _page(back, failed=True), 401
        note_success(tenant=stand, address=адрес, login=account.login)
        return rotate(account, back)

    @app.post(CONFIRM_GOOGLE_PATH)
    def reauth_confirm_google() -> Response:
        refuse_foreign_origin()
        return begin_google(safe_back(request.form.get("next")))
