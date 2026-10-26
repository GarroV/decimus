"""Заголовки безопасности админки: один набор на КАЖДЫЙ ответ (#489).

Один модуль и один крючок `after_request`, а не заголовок у отдельных
маршрутов: страница отказа, редирект входа и картинка кадра — такие же ответы
админки, и защита, которую ставят по одному, первой забывается на новом.

Что и почему:

* **`Content-Security-Policy`** — браузер исполняет только скрипты из своих
  статических файлов. Встроенных `<script>` с кодом и обработчиков `on*=` в
  шаблонах нет (сторожит `tests/test_web_security_headers.py`), поэтому
  `'unsafe-inline'` для скриптов не нужен: внедрённая в страницу строка
  исполняться не будет.
* **`style-src 'unsafe-inline'`** — осознанное исключение. Столбики «Обзора»,
  «Страны», карточки проверки и пиццерии рисуются атрибутом `style` с числом
  из данных (`flex`, `height`); класса на каждое значение не бывает. Стили
  кода не исполняют, а для подмены разметки нужен тот же XSS, который закрыт
  правилом для скриптов.
* **`form-action`** — свои формы плюс `accounts.google.com`: «Черновик в
  Gmail» у письма и «Отправить» у предписания отправляют форму, а сервер
  отвечает переходом к согласию Google. Браузер проверяет `form-action` и на
  таком переходе, без этого источника кнопка молча не сработала бы.
  `*.google.com` — потому что цепочка согласия может продолжиться переходом
  на другой поддомен Google.
* **`frame-ancestors 'none'` и `X-Frame-Options: DENY`** — чужая страница не
  покажет нашу в рамке (подмена нажатий); второй — для просмотрщиков, которые
  не знают первого.
* **`Strict-Transport-Security`** — только по настройке `WEB_HSTS=1`: браузер
  помнит его год, и стенд без сертификата он закрыл бы на этот год.
"""

from __future__ import annotations

from flask import Flask, Response, request

from . import oauth, walk_auth

#: Политика источников. Всё своё; исключения названы и объяснены выше.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' https://accounts.google.com https://*.google.com",
        "frame-ancestors 'none'",
    )
)

#: Согласие OAuth (D417): после «Разрешить» форма уходит редиректом на адрес
#: возврата Claude, а `form-action` браузер проверяет и на редиректах формы.
#: Поэтому на ответах согласия к своим источникам добавлены ровно адреса
#: возврата Claude (`oauth_store.redirect_uri_allowed`), и только там.
OAUTH_FORM_ACTION = "https://claude.ai https://claude.com http://localhost:* http://127.0.0.1:*"

OAUTH_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace(
    "form-action 'self' https://accounts.google.com https://*.google.com",
    f"form-action 'self' https://accounts.google.com https://*.google.com {OAUTH_FORM_ACTION}",
)

#: Камера, микрофон и место админке не нужны: экраны их не просят, и
#: внедрённый код не должен суметь попросить от её имени.
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"

#: Мини-апп обхода снимает нарушение своей камерой (D514): на Android телеграм
#: не открывает камеру по `capture`. Камера — только своему адресу, без рамок.
WALK_PERMISSIONS_POLICY = "camera=(self), microphone=(), geolocation=()"

#: Год — срок, который браузеры и списки предзагрузки считают рабочим.
#: Без `includeSubDomains`: стенд живёт на имени площадки, чьи соседние имена
#: не наши.
#: Мини-апп обхода (#418) — единственная страница, которую показывают в рамке:
#: Telegram открывает её во встроенном окне, а веб-клиент Telegram — во
#: `<iframe>` со своего домена. Поэтому у неё своя политика, а не дыра в общей:
#: рамка разрешена только доменам Telegram, скрипт — только свой и
#: `telegram-web-app.js` с telegram.org. `X-Frame-Options` у неё нет вовсе:
#: значения «разрешить этим доменам» у заголовка не бывает, а `DENY` закрыл
#: бы веб-клиент Telegram.
WALK_ENDPOINTS = walk_auth.ENDPOINTS

WALK_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' https://telegram.org",
        "style-src 'self' 'unsafe-inline'",
        # blob: — превью кадра, снятого на телефоне, до и после отправки (D312).
        "img-src 'self' blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors https://web.telegram.org https://*.telegram.org",
    )
)

HSTS_MAX_AGE = 31_536_000

#: Заголовки, одинаковые для каждого ответа.
BASE_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": PERMISSIONS_POLICY,
}

WALK_HEADERS: dict[str, str] = {
    **{ключ: значение for ключ, значение in BASE_HEADERS.items() if ключ != "X-Frame-Options"},
    "Content-Security-Policy": WALK_CONTENT_SECURITY_POLICY,
    "Permissions-Policy": WALK_PERMISSIONS_POLICY,
}


#: Страницы, которые браузер не кэширует: экран людей показывает новый пароль один
#: раз, «Настройки» — токен Claude и ссылку привязки бота (D447).
NO_STORE_PREFIXES = ("/users", "/settings", "/administration")

#: Исключение из правила выше: своё фото из Google (D468) отдаётся с
#: `private, max-age` и версией в адресе — без кэша браузера оно перекачивалось
#: бы на каждой странице. Секретов в нём нет, общий кэш закрыт `private`.
CACHEABLE_ENDPOINTS = frozenset({"settings_avatar"})


def install(app: Flask, *, hsts: bool, demo: bool = False) -> None:
    """Повесить заголовки на каждый ответ приложения.

    `demo` — стенд открытого демо (D524): мини-апп обхода показывается там в
    рамке телефона на своей же странице `/demo/app`, поэтому рамке разрешён и
    свой домен. На проде рамка — только Telegram.
    """
    заголовки = dict(BASE_HEADERS)
    обход = dict(WALK_HEADERS)
    if demo:
        обход["Content-Security-Policy"] = WALK_CONTENT_SECURITY_POLICY.replace(
            "frame-ancestors ", "frame-ancestors 'self' ", 1
        )
    if hsts:
        заголовки["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE}"
        обход["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE}"

    @app.after_request
    def _security_headers(response: Response) -> Response:
        if request.endpoint in WALK_ENDPOINTS:
            response.headers.pop("X-Frame-Options", None)
            response.headers.update(обход)
        else:
            response.headers.update(заголовки)
        if request.endpoint == oauth.AUTHORIZE_ENDPOINT:
            response.headers["Content-Security-Policy"] = OAUTH_CONTENT_SECURITY_POLICY
        путь = request.path
        if request.endpoint not in CACHEABLE_ENDPOINTS and any(
            путь == p or путь.startswith(f"{p}/") for p in NO_STORE_PREFIXES
        ):
            # Свой заголовок маршрута с `no-store` не затирается: страница ключа
            # «Подключений» отдаёт `private, no-store` (D425).
            if "no-store" not in response.headers.get("Cache-Control", ""):
                response.headers["Cache-Control"] = "no-store"
        return response
