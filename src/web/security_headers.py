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
  Gmail» отправляет форму письма, а сервер отвечает переходом к согласию
  Google. Браузер проверяет `form-action` и на таком переходе, без этого
  источника кнопка молча не сработала бы. `*.google.com` — потому что цепочка
  согласия может продолжиться переходом на другой поддомен Google.
* **`frame-ancestors 'none'` и `X-Frame-Options: DENY`** — чужая страница не
  покажет нашу в рамке (подмена нажатий); второй — для просмотрщиков, которые
  не знают первого.
* **`Strict-Transport-Security`** — только по настройке `WEB_HSTS=1`: браузер
  помнит его год, и стенд без сертификата он закрыл бы на этот год.
"""

from __future__ import annotations

from flask import Flask, Response

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

#: Камера, микрофон и место админке не нужны: экраны их не просят, и
#: внедрённый код не должен суметь попросить от её имени.
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"

#: Год — срок, который браузеры и списки предзагрузки считают рабочим.
#: Без `includeSubDomains`: стенд живёт на имени площадки, чьи соседние имена
#: не наши.
HSTS_MAX_AGE = 31_536_000

#: Заголовки, одинаковые для каждого ответа.
BASE_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": PERMISSIONS_POLICY,
}


def install(app: Flask, *, hsts: bool) -> None:
    """Повесить заголовки на каждый ответ приложения."""
    заголовки = dict(BASE_HEADERS)
    if hsts:
        заголовки["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE}"

    @app.after_request
    def _security_headers(response: Response) -> Response:
        response.headers.update(заголовки)
        return response
