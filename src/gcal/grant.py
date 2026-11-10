"""Отключить календарь: убрать события, отозвать ключ у Google, стереть у себя (D741, #1590).

Порядок важен. Ключ у Google отзывается ДО стирания у нас: стёртый без отзыва остался бы
действующим доступом, о котором мы больше не знаем. Отозвать не удалось (сеть, Google
отказал по иной причине) — подключение остаётся, человек видит «не вышло, повторите».
Ключ не открылся (сменили `SECRETS_KEY`) — отзывать нечем, запись стирается.
"""

from __future__ import annotations

import logging
import urllib.request

from src.db import calendar_store, secret_crypto

from .client import (
    DEAD_GRANT_CODES,
    CalendarError,
    ClientKeys,
    Opener,
    access_token,
    delete_event,
    keys_from_env,
    revoke,
)

logger = logging.getLogger(__name__)

NONE = "none"
OFF = "off"
FAILED = "failed"
#: Ключ у нас не открылся (сменили `SECRETS_KEY`): отозвать его у Google нечем, запись стёрта, а
#: человеку сказано отозвать доступ в настройках аккаунта Google самому.
REVOKE_MANUALLY = "revoke_manually"


def disconnect(
    user_id: str, *, keys: ClientKeys | None = None, opener: Opener = urllib.request.urlopen
) -> str:
    """Отключить календарь.

    Ответ: `off`, `none` (не было), `failed` (ключ не отозван — подключение остаётся) или
    `revoke_manually` (ключ не открылся: запись стёрта, отозвать у Google нужно самому).
    Отзыв клиентских реквизитов не требует (`/revoke` принимает один токен), поэтому он идёт и
    без `GOOGLE_CLIENT_ID/SECRET`; без них только не снимаются события из календаря.
    """
    if calendar_store.grant_of(user_id) is None:
        return NONE
    ключи = keys or keys_from_env()
    try:
        ключ = calendar_store.refresh_token_of(user_id)
    except secret_crypto.SecretCryptoError:
        logger.warning("календарь: ключ не открылся — отзыв у Google только вручную")
        calendar_store.delete_grant(user_id)
        return REVOKE_MANUALLY
    if ключ is not None:
        if ключи is not None:
            _remove_events(user_id, ключи, ключ, opener)
        try:
            revoke(ключ, opener=opener)
        except CalendarError as сбой:
            logger.warning("календарь: ключ не отозван у Google (%s)", сбой.code)
            return FAILED
    calendar_store.delete_grant(user_id)
    return OFF


def _remove_events(user_id: str, keys: ClientKeys, refresh: str, opener: Opener) -> None:
    """Снять события, которые мы ставили: после отключения их больше никто не ведёт.

    Сбой здесь отключение не задерживает: события остаются в календаре человека, и убрать их
    он может сам.
    """
    события = calendar_store.events_of(user_id)
    if not события:
        return
    try:
        токен = access_token(keys, refresh, opener=opener)
    except CalendarError as сбой:
        if сбой.code not in DEAD_GRANT_CODES:
            logger.warning("календарь: события при отключении не сняты (%s)", сбой.code)
        return
    for событие in события:
        try:
            delete_event(токен, событие.event_id, opener=opener)
        except CalendarError as сбой:
            logger.warning("календарь: событие при отключении не снято (%s)", сбой.code)
