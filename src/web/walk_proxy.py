"""Адреса мини-аппа обхода в админке — передача сервису обхода, без своей логики.

Снаружи у продукта один вход (прокси площадки → админка), и адрес мини-аппа,
который бот даёт кнопкой (`BOT_WALK_URL`), — адрес админки. Но писать в идущую
проверку админка не может и не должна: том состояния у неё `:ro`. Пишет
отдельный сервис обхода (`walk_app.py`, свой контейнер, том на запись), и
админка передаёт ему запросы `/tg/walk*` как есть.

Что передаётся: метод, путь вместе с префиксом площадки (`SCRIPT_NAME`) — сервис
обхода настроен тем же `WEB_URL_PREFIX` и собирает ссылки страницы с ним, —
тело и три заголовка: тип тела, подпись Telegram, язык. Назад — код, тело,
тип и `Cache-Control`; заголовки безопасности ставит админка сама, по тем же
именам адресов (`security_headers.WALK_ENDPOINTS`).

Сервис молчит — 503 словами экрана, а не трассировка: аудитор на точке должен
увидеть «сервер недоступен», а не страницу ошибки прокси.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request

from flask import Flask, Response, jsonify, request

from src.domain.uploads import MAX_UPLOAD_BYTES

from .texts import UI_LANGS
from .texts_walk import WALK_TEXTS
from .walk_auth import (
    DATA_ENDPOINT,
    DATA_PATH,
    FINDING_ENDPOINT,
    FINDING_PATH,
    INFO_ENDPOINT,
    INFO_PATH,
    PAGE_ENDPOINT,
    PAGE_PATH,
    PHOTO_ENDPOINT,
    PHOTO_PATH,
    PHOTO_VIEW_ENDPOINT,
    PHOTO_VIEW_PATH,
    SUGGEST_ENDPOINT,
    SUGGEST_PATH,
)

logger = logging.getLogger(__name__)

#: Сколько ждать сервис обхода. Запись идёт движком под замком, а замок ждёт
#: до 30 с (`domain.state.LOCK_TIMEOUT_SEC`): ответ раньше этого срока был бы
#: отказом при работающей записи.
UPSTREAM_TIMEOUT_SEC = 45.0

#: Заголовки запроса, которые нужны сервису обхода. Остальное не передаётся:
#: куки админки и прочее сервису не нужны и не должны до него доходить.
FORWARDED_REQUEST_HEADERS = ("Content-Type", "X-Telegram-Init-Data", "Accept-Language")

#: Заголовки ответа, которые возвращаются как есть.
FORWARDED_RESPONSE_HEADERS = ("Content-Type", "Cache-Control")

# Без системных прокси: сервис обхода живёт во внутренней сети стенда, и
# `HTTP_PROXY` в окружении увёл бы подпись Telegram и кадры наружу.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _unavailable(ui_lang: str) -> tuple[Response, int]:
    lang = ui_lang if ui_lang in UI_LANGS else "en"
    texts = {key: entry[lang] for key, entry in WALK_TEXTS.items()}
    return jsonify({"error": "unavailable", "texts": texts}), 503


def forward(upstream: str, ui_lang: str) -> Response | tuple[Response, int]:
    """Передать текущий запрос сервису обхода и вернуть его ответ."""
    url = f"{upstream}{request.script_root}{request.path}"
    if request.query_string:
        url += "?" + request.query_string.decode("latin-1")
    headers = {
        name: value
        for name in FORWARDED_REQUEST_HEADERS
        if (value := request.headers.get(name)) is not None
    }
    body = request.get_data(cache=False) if request.method == "POST" else None
    outgoing = urllib.request.Request(url, data=body, headers=headers, method=request.method)  # noqa: S310 — адрес из настроек, только http (config._parse_walk_upstream)
    try:
        with _OPENER.open(outgoing, timeout=UPSTREAM_TIMEOUT_SEC) as got:
            status, raw, got_headers = got.status, got.read(), got.headers
    except urllib.error.HTTPError as exc:
        status, raw, got_headers = exc.code, exc.read(), exc.headers
    except (urllib.error.URLError, OSError) as exc:
        logger.warning("Обход: сервис обхода %s не ответил — %s", upstream, exc)
        return _unavailable(ui_lang)
    answer = Response(raw, status=status)
    for name in FORWARDED_RESPONSE_HEADERS:
        value = got_headers.get(name)
        if value is not None:
            answer.headers[name] = value
    return answer


def install(app: Flask, *, upstream: str | None, ui_lang: str) -> None:
    """Повесить адреса обхода, передающие сервису обхода. Без адреса сервиса — не вешать ничего."""
    if upstream is None:
        return
    target = upstream  # сужение типа не доходит до замыкания

    def route(path: str, endpoint: str, method: str, *, max_body: int | None = None) -> None:
        def view() -> Response | tuple[Response, int]:
            if max_body is not None:
                request.max_content_length = max_body
            return forward(target, ui_lang)

        app.add_url_rule(path, endpoint=endpoint, view_func=view, methods=[method])

    route(PAGE_PATH, PAGE_ENDPOINT, "GET")
    route(DATA_PATH, DATA_ENDPOINT, "POST")
    route(PHOTO_PATH, PHOTO_ENDPOINT, "POST", max_body=MAX_UPLOAD_BYTES)
    route(PHOTO_VIEW_PATH, PHOTO_VIEW_ENDPOINT, "POST")
    route(FINDING_PATH, FINDING_ENDPOINT, "POST")
    route(INFO_PATH, INFO_ENDPOINT, "POST")
    route(SUGGEST_PATH, SUGGEST_ENDPOINT, "POST")
