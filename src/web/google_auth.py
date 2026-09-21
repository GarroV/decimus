"""Вход в админку по учётке Google (T332, D163, D168).

Google здесь подтверждает ровно одно: человек владеет почтой. Кому можно в
админку, решает не он, а строка в `web_users` — поэтому незнакомая почта
получает отказ, а не заводит учётку (`db.web_access.find_by_email`).

**Своей библиотеки под это не берём.** Нужны один GET-редирект и один POST на
обмен кода — это `urllib.request` из стандартной поставки. Тянуть ради двух
запросов зависимость, которую потом обновлять и проверять, здесь не за что.

**Подпись `id_token` не проверяется, и это не упущение.** Токен приходит не от
браузера, а прямым ответом token endpoint по TLS, с нашим `client_secret` в
запросе — то есть канал уже доверенный, и Google прямо разрешает в этом случае
пропустить проверку подписи. Что проверить обязательно — `aud`, `iss`, срок и
подтверждённость почты: без них чужое приложение подсунуло бы свой токен.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

GOOGLE_CLIENT_ID_VAR = "GOOGLE_CLIENT_ID"
GOOGLE_CLIENT_SECRET_VAR = "GOOGLE_CLIENT_SECRET"  # noqa: S105 — ИМЯ переменной
GOOGLE_REDIRECT_URI_VAR = "GOOGLE_REDIRECT_URI"

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 — адрес, не секрет

#: Три неконфиденциальных скоупа: кто это и какая у него почта. Проверки
#: Google они не требуют. Почтовый `gmail.compose` сюда НЕ добавляется — он
#: чувствительный и тянет за собой проверку приложения (Q060, Q061).
SCOPES = ("openid", "email", "profile")

#: Обе формы издателя, которые Google выдаёт исторически. Список закрытый:
#: `iss` — это и есть ответ на вопрос «кто подписал», и принимать произвольного
#: издателя значит не проверять ничего.
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

#: Запас на расхождение часов между нами и Google. Без него токен, выписанный
#: секунду назад, отвергался бы на машине, спешащей на пару секунд.
CLOCK_SKEW_SECONDS = 60

#: Сколько ждём Google. Без предела запрос висит до упора, и вместе с ним
#: висит поток, обслуживающий человека.
NETWORK_TIMEOUT_SECONDS = 10


class GoogleAuthError(Exception):
    """Вход через Google не состоялся. Человеку показывается общий отказ."""


@dataclass(frozen=True)
class GoogleSettings:
    """Реквизиты приложения. Живут в окружении площадки, не в репозитории."""

    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class GoogleIdentity:
    """Что Google рассказал о вошедшем. Больше нам от него ничего не нужно."""

    email: str
    email_verified: bool


def load_google_settings(env: Mapping[str, str] | None = None) -> GoogleSettings | None:
    """Реквизиты из окружения. `None` — вход через Google не настроен.

    Не отказ, а именно «его нет»: на стенде без реквизитов админка обязана
    работать как работала, с паролем. Иначе забытая переменная превращала бы
    обновление в отказ входа для всех.
    """
    import os

    src = os.environ if env is None else env
    client_id = (src.get(GOOGLE_CLIENT_ID_VAR) or "").strip()
    client_secret = (src.get(GOOGLE_CLIENT_SECRET_VAR) or "").strip()
    redirect_uri = (src.get(GOOGLE_REDIRECT_URI_VAR) or "").strip()
    if not (client_id and client_secret and redirect_uri):
        return None
    return GoogleSettings(
        client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
    )


def new_state() -> str:
    """Случайная метка захода, она же защита от подделки возврата (CSRF).

    Кладётся в сессию и сверяется на возврате. Без неё чужая страница могла бы
    привести человека на наш `callback` со своим кодом и войти его браузером.
    """
    return secrets.token_urlsafe(32)


def authorization_url(settings: GoogleSettings, *, state: str) -> str:
    """Адрес, куда уводим человека на согласие."""
    параметры = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
        # Своя почта у человека одна, но аккаунтов в браузере бывает несколько,
        # и молчаливый вход «не тем» аккаунтом выглядит как отказ доступа.
        "prompt": "select_account",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urllib.parse.urlencode(параметры)}"


def exchange_code(settings: GoogleSettings, *, code: str) -> GoogleIdentity:
    """Код возврата → почта вошедшего. Любая осечка — `GoogleAuthError`."""
    запрос = urllib.request.Request(
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
    except Exception as сбой:  # сеть, разбор, отказ Google — для входа это одно и то же
        raise GoogleAuthError(f"обмен кода не удался: {type(сбой).__name__}") from сбой

    id_token = тело.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise GoogleAuthError("в ответе Google нет id_token")
    return identity_from_id_token(id_token, client_id=settings.client_id)


def identity_from_id_token(raw: str, *, client_id: str, now: float | None = None) -> GoogleIdentity:
    """Разобрать и проверить `id_token`. Отдельной функцией — её и тестируем.

    Сеть тут не нужна: всё, что делает проверка, — читает полезную нагрузку и
    сверяет её с тем, чего мы ждём. Поэтому она чистая, а тест на неё не ходит
    наружу и не зависит от настроения Google.
    """
    нагрузка = _payload(raw)
    сейчас = time.time() if now is None else now

    if нагрузка.get("iss") not in ISSUERS:
        raise GoogleAuthError("токен выписан не Google")
    if нагрузка.get("aud") != client_id:
        raise GoogleAuthError("токен выписан не нашему приложению")

    срок = нагрузка.get("exp")
    if not isinstance(срок, (int, float)) or срок + CLOCK_SKEW_SECONDS < сейчас:
        raise GoogleAuthError("срок действия токена истёк")

    почта = нагрузка.get("email")
    if not isinstance(почта, str) or not почта.strip():
        raise GoogleAuthError("в токене нет почты")

    # `email_verified` — не украшение: без него вход отдаётся всякому, кто
    # завёл аккаунт на чужой адрес и не подтвердил его.
    подтверждена = нагрузка.get("email_verified")
    if подтверждена is not True:
        raise GoogleAuthError("почта в аккаунте Google не подтверждена")

    return GoogleIdentity(email=почта.strip().lower(), email_verified=True)


def _payload(raw: str) -> dict[str, Any]:
    """Средняя часть JWT как словарь. Подпись здесь не разбирается (см. модуль)."""
    части = raw.split(".")
    if len(части) != 3:
        raise GoogleAuthError("id_token не похож на JWT")
    середина = части[1]
    # base64url без выравнивания — добиваем '=' сами, иначе стандартный
    # декодер откажется от валидного токена.
    середина += "=" * (-len(середина) % 4)
    try:
        разобрано = json.loads(base64.urlsafe_b64decode(середина))
    except Exception as сбой:
        raise GoogleAuthError("нагрузка id_token не читается") from сбой
    if not isinstance(разобрано, dict):
        raise GoogleAuthError("нагрузка id_token не объект")
    return разобрано
