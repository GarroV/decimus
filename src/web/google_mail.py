"""Черновик письма партнёру в почте вошедшего (D174, D176, #332).

Отправки из системы нет и здесь не появляется: письмо кладётся в **черновики**,
дальше человек отправляет его из своей почты сам. Это прямое решение владельца
(D169), и оно же убирает целый класс вопросов — кто подписал, с какого адреса
ушло, что именно лежит в отправленных.

**Почему согласие спрашивается отдельно, а не на входе.** `gmail.compose` —
чувствительный скоуп: запрошенный на входе, он показывал бы экран доступа к
почте каждому, кто открывает админку, включая тех, кто писем не пишет вовсе.
Google для этого и держит инкрементальное согласие: вход остаётся на трёх
неконфиденциальных скоупах (`src/web/google_auth.py`), а почтовый добирается
в тот момент, когда человек впервые уводит письмо в черновики.

**Токен живёт в сессии и нигде больше.** `refresh_token` мы не просим и не
храним: это долговременный доступ к чужой почте в нашей базе, и он был бы
нужен только фоновой отправке, которой нет. Черновик создаётся синхронно,
пока человек здесь, — часового `access_token` на это хватает с запасом.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

from src.web.google_auth import (
    AUTHORIZATION_ENDPOINT,
    NETWORK_TIMEOUT_SECONDS,
    TOKEN_ENDPOINT,
    GoogleSettings,
)

#: Право завести черновик и ничего больше: ни чтения ящика, ни отправки.
#: `gmail.modify` и `https://mail.google.com/` тоже подошли бы — и оба дают
#: доступ к переписке человека, который нам не нужен ни для чего.
DRAFT_SCOPE = "https://www.googleapis.com/auth/gmail.compose"

DRAFTS_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"

#: Заголовок темы по языку ПИСЬМА (не интерфейса): партнёр читает письмо на
#: своём языке, и тема — первое, что он видит.
SUBJECT_TITLES = {"ru": "Проверка пиццерии", "en": "Pizzeria audit", "sr": "Провера пицерије"}


class GoogleMailError(Exception):
    """Черновик не завёлся. Текст показывается человеку и объясняет, что делать."""


def consent_url(settings: GoogleSettings, *, state: str, login_hint: str) -> str:
    """Адрес, где человек разрешает нам класть черновик в свою почту."""
    параметры = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": DRAFT_SCOPE,
        "state": state,
        # Без этого Google выдаёт токен ТОЛЬКО на почтовый скоуп, забыв про
        # выданные на входе, — и следующий вход снова просит согласия.
        "include_granted_scopes": "true",
        # Согласие на чувствительный скоуп молча не выдаётся: без явного
        # запроса Google вернёт прежний токен без почтового права, и отказ
        # всплывёт уже на создании черновика.
        "prompt": "consent",
        # Аккаунтов в браузере бывает несколько, а черновик обязан лечь в
        # почту ТОГО, кто вошёл (D176), а не того, кто первый в списке.
        "login_hint": login_hint,
        # `refresh_token` не просим (см. модуль): online-доступ и есть отказ
        # от долговременного ключа к чужой почте.
        "access_type": "online",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(параметры)}"


def exchange_code_for_token(settings: GoogleSettings, *, code: str) -> str:
    """Код возврата → `access_token` на почтовый скоуп."""
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
        raise GoogleMailError(f"обмен кода не удался: {type(сбой).__name__}") from сбой

    токен = тело.get("access_token")
    if not isinstance(токен, str) or not токен:
        raise GoogleMailError("Google не выдал доступ к почте")
    return токен


def draft_subject(*, city: str, date: str, lang: str) -> str:
    """Тема черновика из шапки проверки.

    Пустые части выбрасываются целиком, а не подставляются прочерком: тема
    вида «Проверка пиццерии ·  · 2026-09-12» уходит партнёру как есть, и
    чинить её будет уже человек в почте.
    """
    части = [SUBJECT_TITLES.get(lang, SUBJECT_TITLES["en"]), city.strip(), date.strip()]
    return " · ".join(часть for часть in части if часть)


def mime_message(*, to: str, subject: str, body: str) -> str:
    """Письмо как `raw` для Gmail: MIME в base64url без выравнивания."""
    if not body.strip():
        raise GoogleMailError("письмо пустое — черновик не заводится")

    письмо = EmailMessage()
    # Заголовки кириллицей кодирует сам `EmailMessage` (RFC 2047); собранный
    # руками заголовок с сырым UTF-8 Gmail примет, а почтовые клиенты
    # покажут кракозябрами.
    письмо["Subject"] = subject
    # Пустой адресат — обычное дело: контакт партнёра заполняет мастер бота, и
    # он не обязателен. Заголовок `To:` с пустым значением делает черновик
    # неотправляемым, поэтому его просто нет.
    if to.strip():
        письмо["To"] = to.strip()
    письмо.set_content(body)

    return base64.urlsafe_b64encode(письмо.as_bytes()).decode().rstrip("=")


def create_draft(
    access_token: str,
    *,
    to: str,
    subject: str,
    body: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    """Положить письмо в черновики вошедшего. Возвращает номер черновика.

    `opener` — точка подмены для проверки: сам разговор с Gmail тривиален, а
    вот разбор его ответов решает, увидит ли человек внятную причину отказа.
    """
    сырое = mime_message(to=to, subject=subject, body=body)
    запрос = urllib.request.Request(
        DRAFTS_ENDPOINT,
        data=json.dumps({"message": {"raw": сырое}}).encode(),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener(запрос, timeout=NETWORK_TIMEOUT_SECONDS) as ответ:
            тело = json.loads(ответ.read())
    except Exception as сбой:
        код = getattr(сбой, "code", None)
        if код == 403:
            raise GoogleMailError(
                "Google не дал положить черновик: согласие на доступ к почте не выдано или отозвано"
            ) from сбой
        if код == 401:
            raise GoogleMailError("доступ к почте истёк — потребуется согласие заново") from сбой
        raise GoogleMailError(f"черновик не создан: {type(сбой).__name__}") from сбой

    номер = тело.get("id") if isinstance(тело, dict) else None
    if not isinstance(номер, str) or not номер:
        # Ответ без номера значит, что черновика в почте нет. Считать это
        # успехом — ровно тот молчаливый сбой, за который человек потом
        # ищет письмо в пустых черновиках.
        raise GoogleMailError("Gmail ответил без номера черновика")
    return номер
