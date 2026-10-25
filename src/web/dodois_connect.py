"""Публичная страница входа в Dodo IS по ссылке-приглашению (D640, #951).

Главный админ выдаёт коллеге страны ссылку (`dodois_screen.py`); коллега открывает её БЕЗ
входа в decimus, читает, что просит приложение, жмёт «Войти в Dodo IS» и подтверждает вход
на сайте Dodo IS. Адреса открыты заслону входа (`auth.OPEN_ENDPOINTS`): доступ даёт токен
в адресе. Заслону происхождения они НЕ открыты — кнопка стоит в форме нашей же страницы.

**Заслоны, по порядку.**
1. Предел попыток по адресу (`web_throttle`, тот же счётчик, что у пароля): запертый адрес
   получает тот же 404.
2. Форма токена, затем хэш и сверка за постоянное время (`dodois_logins.find_invite`).
3. Ссылка жива: не погашена, не отозвана, не истекла, страна — та, что записана в ней.
4. Любой «нет» — один и тот же нейтральный 404, без подсказки, чем плох токен; неудача
   записывается в счётчик адреса.

**GET ничего не начинает.** Мессенджеры раскрывают ссылки ботами-превью: открытие страницы
не запускает вход и не тратит код Dodo IS. Вход начинает только POST с кнопки
(`dodois.flow.start`); страница сама ждёт результата, опрашивая `status` своего сервера, а
код устройства в браузер не уходит. Только что законченный вход (десять минут) виден по той же
ссылке как «Готово», хотя ссылка уже погашена, — иначе страница ответила бы 404 в момент успеха.

**Ответы без кэша, `Referrer-Policy: no-referrer`** (токен в адресе не должен утечь в Referer),
сторонних ресурсов страница не грузит. В демо адреса закрыты (`demo_entry.LOCKED_ENDPOINTS`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from flask import Flask, Response, abort, jsonify, make_response, render_template, request

from src.db import dodois_logins, web_throttle
from src.db.errors import DbError
from src.dodois import flow, service
from src.dodois.client import DodoisError
from src.domain import dodois as rules
from src.domain.dodois import Invite

from .config import Settings
from .journal import client_ip
from .origin import refuse_foreign_origin
from .remote import UNKNOWN

_log = logging.getLogger(__name__)

PATH = "/dodois/connect/<token>"
PAGE_ENDPOINT = "dodois_connect"
START_ENDPOINT = "dodois_connect_start"
STATUS_ENDPOINT = "dodois_connect_status"
ENDPOINTS = frozenset({PAGE_ENDPOINT, START_ENDPOINT, STATUS_ENDPOINT})

#: Раз в сколько секунд страница спрашивает наш сервер, чем кончился вход.
POLL_EVERY_SEC = 3


def _resolve(conf: Settings, token: str) -> tuple[Invite, flow.Flow | None] | None:
    """Приглашение по токену из адреса либо `None` (одинаково для любого «нет»).

    Ссылка, погашенная только что этим же входом, ещё узнаётся — чтобы страница показала «Готово».
    """
    address = client_ip(conf) or UNKNOWN
    tenant = conf.tenant
    try:
        if web_throttle.address_verdict(tenant=tenant, address=address).locked:
            return None
        found = _find(token)
        shown = None if found is None else _alive(found)
        if shown is None:
            web_throttle.note_address_failure(tenant=tenant, address=address)
        return shown
    except DbError:
        _log.warning("dodois: ссылка не проверилась (база отказала)")
        return None


def _find(token: str) -> Invite | None:
    if not rules.token_shape_ok(token):
        return None
    return dodois_logins.find_invite(rules.hash_token(token))


def _alive(invite: Invite) -> tuple[Invite, flow.Flow | None] | None:
    current = flow.current(invite.id)
    if invite.usable(datetime.now(UTC)):
        return invite, current
    if invite.used_at is not None and current is not None and current.state == flow.DONE:
        return invite, current
    return None


def _view(invite: Invite, current: flow.Flow | None, token: str) -> dict[str, Any]:
    state = current.state if current is not None else flow.IDLE
    return {
        "country": invite.country,
        "state": state,
        "reason": current.reason if current is not None else "",
        "user_code": current.user_code if state == flow.PENDING and current else "",
        "link": current.link if state == flow.PENDING and current else "",
        "can_start": state in (flow.IDLE, *flow.RESTARTABLE),
        "status_url": f"{request.script_root}/dodois/connect/{token}/status",
        "start_url": f"{request.script_root}/dodois/connect/{token}/start",
        "poll_sec": POLL_EVERY_SEC,
    }


def _page(invite: Invite, current: flow.Flow | None, token: str, *, error: str = "") -> Response:
    body = render_template("dodois/connect.html", error=error, **_view(invite, current, token))
    return make_response(body, 503 if error else 200)


def install(app: Flask, conf: Settings) -> None:
    @app.get(PATH, endpoint=PAGE_ENDPOINT)
    def dodois_connect(token: str) -> Response:
        shown = _resolve(conf, token)
        if shown is None:
            abort(404)
        return _page(shown[0], shown[1], token)

    @app.post(PATH + "/start", endpoint=START_ENDPOINT)
    def dodois_connect_start(token: str) -> Response:
        refuse_foreign_origin()
        shown = _resolve(conf, token)
        if shown is None:
            abort(404)
        invite, current = shown
        if not invite.usable(datetime.now(UTC)):
            abort(404)  # погашенная ссылка (даже только что) нового входа не начинает
        creds = service.credentials()
        if creds is None:
            return _page(invite, current, token, error="no_keys")
        try:
            started = flow.start(invite, creds=creds, ip=client_ip(conf))
        except DodoisError as exc:
            _log.warning("dodois: вход по ссылке не начался (%s)", exc.kind)
            return _page(invite, current, token, error=exc.kind)
        return _page(invite, started, token)

    @app.get(PATH + "/status", endpoint=STATUS_ENDPOINT)
    def dodois_connect_status(token: str) -> Response:
        shown = _resolve(conf, token)
        if shown is None:
            abort(404)
        current = shown[1]
        return jsonify({"state": current.state if current is not None else flow.IDLE})

    @app.after_request
    def _public_headers(response: Response) -> Response:
        if request.endpoint in ENDPOINTS:
            # Токен в адресе: ни в Referer, ни в кэш браузера и прокси.
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
        return response
