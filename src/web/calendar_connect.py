"""Подключить и отключить Google Календарь из «Настроек» (D740, D741, #1590).

Согласие у Google идёт тем же клиентом и тем же адресом возврата, что у входа и привязки
почты (`/auth/google/callback`): вид захода различает подписанная кука (`KIND`), второго
адреса в консоли Google заводить не нужно. Начало и возврат стоят в `auth.install` рядом с
меткой и реквизитами; здесь — адрес согласия, обмен кода и сверка, чей это доступ.

**Скоуп один — `calendar.events.owned`** (`src/gcal/client.py`; выбор и причина —
`docs/39-calendar-deadline.md`). Вместе с ним спрашиваются `openid email`: из ответа на обмен
читается, КАКОЙ аккаунт выдал доступ, и чужой аккаунт получает отказ (как у черновика Gmail,
F-018): событие должно лечь в календарь вошедшего, а не того, кого выбрали в окне Google.

**Ключ продления здесь хранится** (D741: автоматика без человека за экраном; у черновика Gmail
ключа нет). Хранение — `src/db/calendar_store.py`, шифрованное. Запрос `access_type=offline` и
`prompt=consent` обязательны: без второго Google не выдаёт ключ продления повторно, если
согласие уже было.

**Сбой не ломает ничего, кроме этого экрана**: исход возврата — ключ из закрытого списка
(`google_link.RESULTS`), в журнал уходит код причины и метка учётки, не почта.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass

from src.db import calendar_store, secret_crypto
from src.db.errors import DbError
from src.db.web_access import claim_google_sub
from src.domain.log_ids import log_id
from src.domain.tenants import HQ_TENANT, canonical_tenant
from src.gcal.client import (
    EVENTS_SCOPE,
    CalendarError,
    access_token,
    keys_from_env,
    reason_code,
    revoke,
)

from .google_auth import (
    AUTHORIZATION_ENDPOINT,
    NETWORK_TIMEOUT_SECONDS,
    TOKEN_ENDPOINT,
    GoogleAuthError,
    GoogleSettings,
    identity_from_id_token,
)

logger = logging.getLogger(__name__)

#: Вид метки в куке захода: подключение календаря (рядом с `link` и `reauth`).
KIND = "calendar"

CONSENT_SCOPES = ("openid", "email", EVENTS_SCOPE)


def may_connect(tenant: str | None) -> bool:
    """Календарь подключают только учётки УК: события ставятся по проверкам пространства УК."""
    return canonical_tenant(tenant or "") == HQ_TENANT


def nonce_for(state: str) -> str:
    """`nonce` захода, выведенный из метки: токен привязан к ЭТОМУ заходу."""
    return hashlib.sha256(f"google-calendar-nonce:{state}".encode()).hexdigest()


def consent_url(settings: GoogleSettings, *, state: str, login_hint: str) -> str:
    """Адрес, где человек разрешает нам события в своём календаре."""
    параметры = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": " ".join(CONSENT_SCOPES),
        "state": state,
        "nonce": nonce_for(state),
        # Ключ продления нужен фоновой задаче; `prompt=consent` — чтобы Google выдал его
        # и при повторном подключении.
        "access_type": "offline",
        "prompt": "consent",
    }
    if login_hint:
        параметры["login_hint"] = login_hint
    return f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(параметры)}"


@dataclass(frozen=True)
class CalendarConsent:
    """Что выдал Google: ключ продления, чья это почта и какие права выданы."""

    refresh_token: str = ""
    email: str = ""
    subject: str = ""
    nonce: str = ""
    scopes: frozenset[str] = frozenset()


class CalendarConsentError(Exception):
    """Обмен кода не удался; `code` — причина для журнала, без данных человека."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def exchange(settings: GoogleSettings, *, code: str) -> CalendarConsent:
    """Код возврата → ключ продления и аккаунт, выдавший доступ."""
    запрос = urllib.request.Request(  # noqa: S310 — адрес постоянный, схема не из данных
        TOKEN_ENDPOINT,
        data=urllib.parse.urlencode(
            {
                "code": code,
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "redirect_uri": settings.redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(запрос, timeout=NETWORK_TIMEOUT_SECONDS) as ответ:  # noqa: S310
            тело = json.loads(ответ.read())
    except Exception as сбой:
        raise CalendarConsentError(reason_code(сбой)) from сбой
    ключ = тело.get("refresh_token")
    id_token = тело.get("id_token")
    if not isinstance(ключ, str) or not ключ:
        raise CalendarConsentError("no_refresh_token")
    if not isinstance(id_token, str) or not id_token:
        raise CalendarConsentError("no_id_token")
    try:
        кто = identity_from_id_token(id_token, client_id=settings.client_id)
    except GoogleAuthError as сбой:
        raise CalendarConsentError("id_token_refused") from сбой
    выдано = frozenset(str(тело.get("scope") or "").split())
    return CalendarConsent(
        refresh_token=ключ,
        email=кто.email if кто.email_verified else "",
        subject=кто.subject,
        nonce=кто.nonce,
        scopes=выдано,
    )


def _retire_previous_key(user_id: str, new_key: str) -> bool:
    """Отозвать прежний ключ продления перед заменой: старый не должен остаться действующим.

    Сбой отзыва — в лог, подключение не валим. Но отзыв ключа Google может снять и общее
    согласие, из-за чего новый ключ тоже умирает; поэтому после отзыва новый ключ пробуется, и
    если он не работает — подключение не сохраняется (`False`), а человек подключает заново.
    """
    try:
        старый = calendar_store.refresh_token_of(user_id)
    except (DbError, secret_crypto.SecretCryptoError):
        logger.warning("календарь: прежний ключ %s не прочитан — не отозван", log_id(user_id))
        return True
    if not старый or старый == new_key:
        return True
    try:
        revoke(старый)
    except CalendarError as сбой:
        logger.warning("календарь: прежний ключ %s не отозван (%s)", log_id(user_id), сбой.code)
        return True
    keys = keys_from_env()
    if keys is None:
        return True
    try:
        access_token(keys, new_key)
    except CalendarError as сбой:
        logger.warning("календарь: после отзыва прежнего ключа новый не работает (%s)", сбой.code)
        return False
    return True


def finish(*, user_id: str, account_email: str | None, state: str, consent: CalendarConsent) -> str:
    """Проверить выданное и сохранить ключ. Ответ — ключ `google_link.RESULTS`.

    Порядок: тот же заход (`nonce`), тот же аккаунт Google, что привязан к учётке, и право
    на события действительно выдано (в окне согласия его можно снять галочкой).
    """
    кто = log_id(user_id)
    if not consent.nonce or not hmac.compare_digest(
        consent.nonce.encode(), nonce_for(state).encode()
    ):
        logger.warning("календарь: подключение %s — nonce не совпал с меткой захода", кто)
        return "calendar_failed"
    своя = (account_email or "").strip().lower()
    if not своя or not consent.email or consent.email.strip().lower() != своя:
        logger.warning("календарь: подключение %s — доступ выдал не тот аккаунт Google", кто)
        return "calendar_account"
    # Тот же аккаунт Google, что держит учётку (F-027), а не только та же почта.
    if (
        not consent.subject
        or claim_google_sub(consent.email, consent.subject, record=False) != "ok"
    ):
        logger.warning("календарь: подключение %s — номер аккаунта Google не тот", кто)
        return "calendar_account"
    if EVENTS_SCOPE not in consent.scopes:
        logger.info("календарь: подключение %s — право на события не выдано", кто)
        return "calendar_scope"
    if not _retire_previous_key(user_id, consent.refresh_token):
        # Прежний ключ уже отозван: пометить сразу, чтобы экран не показывал «подключён».
        try:
            calendar_store.mark_problem(user_id, "invalid_grant")
        except DbError:
            logger.warning("календарь: пометка отозванного ключа %s не записана", кто)
        return "calendar_failed"
    try:
        calendar_store.save_grant(
            user_id,
            google_email=consent.email,
            scope=EVENTS_SCOPE,
            refresh_token=consent.refresh_token,
        )
    except (DbError, secret_crypto.SecretCryptoError) as сбой:
        logger.error("календарь: подключение %s не сохранено (%s)", кто, type(сбой).__name__)
        return "calendar_db"
    logger.info("календарь: %s подключил Google Календарь", кто)
    return "calendar_on"
