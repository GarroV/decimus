"""Привязка своей почты Google из «Настроек» (D447, D450, D430).

Человек сам привязывает аккаунт Google к своей учётке: «Привязать Google» →
согласие у Google (тот же клиент и тот же адрес возврата, что у входа) →
возврат в `auth.google_callback`, который по виду метки отдаёт заход сюда.

Кому какая почта годится — здесь, и порядок проверок — защита:

1. **Учётка — только из сессии.** Возврат без живой сессии ничего не
   привязывает; ключ учётки ниоткуда не читается.
2. **Почта подтверждена у Google** (`email_verified`) — второй заслон после
   разбора токена, как у входа.
3. **Токен выписан на ЭТОТ заход** — `nonce` в `id_token` равен выведенному из
   метки. Код без него привязан к метке, токен — нет.
4. **Учётка УК — только аккаунт домена компании** (`hd` из
   `GOOGLE_HQ_DOMAINS`, D430/D450). Партнёрам домен не нужен (D430): они входят
   по почтам из списка своего пространства — а этот список и есть почты их
   учёток, которые ставит админ или сам человек отсюда. Чужой адрес сюда не
   поставить: Google подтверждает, что человек владеет почтой.
5. **Метка одноразовая и своя, почта уникальна** — держит база одной функцией
   (`finish_own_google_link`, `0061`): погасить метку своей сессии и записать
   почту под уникальным индексом.

После привязки вход паролем для учётки закрыт (D450) — экран предупреждает об
этом до ухода к Google. В журнал — метка учётки (`log_id`), исход и маска
почты, не адрес.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from flask import redirect, url_for
from werkzeug.wrappers import Response

from src.db import web_own_profile
from src.db.errors import DbError
from src.domain.log_ids import log_id
from src.domain.tenants import HQ_TENANT, canonical_tenant

from .google_auth import GoogleIdentity, hq_domain_ok

logger = logging.getLogger(__name__)

#: Вид метки в куке захода: привязка, а не вход.
LINK_KIND = "link"

#: Параметр адреса «Настроек», которым возврат сообщает исход.
RESULT_PARAM = "google"

#: Исход → ключ текста и тон. Закрытый список: в адрес попадает только ключ,
#: чужое значение показывает ничего.
RESULTS: dict[str, tuple[str, bool]] = {
    "linked": ("settings.google.done.linked", True),
    "unlinked": ("settings.google.done.unlinked", True),
    "cancelled": ("settings.google.done.cancelled", False),
    "failed": ("settings.google.done.failed", False),
    "state": ("settings.google.done.state", False),
    "unverified": ("settings.google.done.unverified", False),
    "domain": ("settings.google.done.domain", False),
    "taken": ("settings.google.done.taken", False),
    "already": ("settings.google.done.already", False),
    "db": ("settings.google.done.db", False),
}


def back_to_settings(result: str | None = None) -> Response:
    """В «Настройки» с исходом в адресе (ключ из `RESULTS`, не текст)."""
    адрес = url_for("settings_page")
    return redirect(f"{адрес}?{RESULT_PARAM}={result}" if result else адрес)


def nonce_for(state: str) -> str:
    """`nonce` захода, выведенный из метки: хранить второе значение не нужно."""
    return hashlib.sha256(f"google-link-nonce:{state}".encode()).hexdigest()


def mask_email(email: str) -> str:
    """Почта для журнала: первая буква и домен. Адрес целиком в INFO не пишется."""
    имя, _, домен = email.partition("@")
    return f"{имя[:1]}***@{домен}" if домен else "***"


def finish(
    *,
    token: str,
    login: str,
    tenant: str,
    state: str,
    identity: GoogleIdentity,
    hq_domains: frozenset[str],
) -> str:
    """Проверить пришедшее от Google и привязать почту. Ответ — ключ `RESULTS`."""
    # Учётка в журнале — меткой, не логином и не кодом пространства (F-015).
    кто = log_id(login)
    if not identity.email_verified:
        logger.info("Google: привязка %s — почта не подтверждена", кто)
        return "unverified"
    if not identity.nonce or not hmac.compare_digest(
        identity.nonce.encode(), nonce_for(state).encode()
    ):
        logger.warning("Google: привязка %s — nonce не совпал с меткой захода", кто)
        return "state"
    if canonical_tenant(tenant) == HQ_TENANT and not hq_domain_ok(identity, hq_domains):
        logger.warning(
            "Google: привязка %s — домен организации %r не в GOOGLE_HQ_DOMAINS",
            кто,
            identity.hosted_domain,
        )
        return "domain"
    try:
        итог = web_own_profile.finish_google_link(token, state=state, email=identity.email)
    except DbError:
        logger.exception("Google: привязка %s — отказ базы", кто)
        return "db"
    if итог == "ok":
        logger.info("Google: %s привязал почту %s", кто, mask_email(identity.email))
        return "linked"
    logger.info("Google: привязка %s не состоялась — %s", кто, итог)
    return {"linked": "already", "session": "state"}.get(итог, итог)
