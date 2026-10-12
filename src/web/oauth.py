"""Сервер авторизации OAuth для подключения Claude к MCP (D417).

claude.ai в браузере, Desktop и телефон подключаются к MCP только через OAuth:
человек вставляет адрес MCP в Claude, тот находит здесь вход, человек входит
своей учёткой decimus и разрешает доступ. Права в MCP после этого решает роль
учётки (`src/mcp/policy.py`).

Поверхности:

* `GET /.well-known/oauth-authorization-server` — метаданные (RFC 8414);
* `POST /oauth/register` — динамическая регистрация клиента (RFC 7591);
* `GET/POST /oauth/authorize` — страница согласия; требует входа;
* `POST /oauth/token` — обмен кода (PKCE S256) и refresh с ротацией.

Хранение и правила (адрес возврата, PKCE) — `src/db/oauth_store.py`, общий
с сервером MCP. Всё включается только при заданных `ADMIN_PUBLIC_URL` и
`MCP_PUBLIC_URL`: без них маршрутов нет вовсе.

**Проверка `Origin` у `/oauth/register` и `/oauth/token` не делается
осознанно.** Их зовёт не браузер человека, а сервер Claude или процесс Claude
Code — заголовка `Origin` там нет, и `refuse_foreign_origin` отказал бы всем.
Подделать их чужой странице нечем: кука сессии им не нужна и не читается,
регистрация ничего не открывает, а обмен требует кода и `code_verifier`,
которых у чужой страницы нет. POST согласия — другое дело: он идёт с куки
вошедшего, и проверка `Origin` на нём стоит.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit

from flask import Flask, jsonify, redirect, render_template, request
from werkzeug.datastructures import MultiDict
from werkzeug.wrappers import Response

from src.db import oauth_store, web_throttle
from src.db.errors import AccessError, OAuthGrantError
from src.domain.public_urls import AUTHORIZATION_SERVER_PATH

from .config import Settings
from .origin import refuse_foreign_origin
from .remote import client_address

AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"  # noqa: S105 — путь адреса, а не токен
REGISTER_PATH = "/oauth/register"

#: Имя маршрута согласия: заслон входа уводит с него на вход и обратно (`auth.py`).
AUTHORIZE_ENDPOINT = "oauth_authorize"

#: Открыты без входа: их зовёт сервер Claude, а не браузер вошедшего.
ENDPOINTS = frozenset({"oauth_metadata", "oauth_register", "oauth_token"})

#: Пределы успешных регистраций клиентов за окно — два, и нужны оба.
#:
#: На адрес — 10 в час. Регистрация открыта без входа; без предела на адрес один
#: перебирающий выбирал общий предел и закрывал подключение всей компании.
#: claude.ai регистрирует клиентов со своих серверов, и адресов у него мало.
#: Переиспользует ли он `client_id`, не проверено; в худшем случае — клиент на
#: каждое подключение, и 10 в час с одного адреса Anthropic значат 10 новых
#: подключений в час. Людей в decimus десятки, подключаются они один раз, а
#: Claude Code регистрируется с машины человека — со своего адреса. Упёршийся
#: получает 429 с `Retry-After` и повторяет позже.
#:
#: Общий — 1000 в час: чтобы выбрать его, нужна сотня адресов, а брошенных
#: клиентов убирает чистка (`oauth_store.purge_stale`) — таблица не растёт.
REGISTRATION_WINDOW = timedelta(hours=1)
REGISTRATIONS_PER_ADDRESS = 10
REGISTRATIONS_PER_WINDOW = 1000

GRANT_TYPES = ("authorization_code", "refresh_token")

logger = logging.getLogger(__name__)

_JSON_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def metadata(issuer: str) -> dict[str, Any]:
    """Метаданные сервера авторизации (RFC 8414). CIMD не объявляется — Claude идёт через DCR."""
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}{AUTHORIZE_PATH}",
        "token_endpoint": f"{issuer}{TOKEN_PATH}",
        "registration_endpoint": f"{issuer}{REGISTER_PATH}",
        "response_types_supported": ["code"],
        "grant_types_supported": list(GRANT_TYPES),
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [oauth_store.SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }


def with_query(uri: str, **params: str | None) -> str:
    """Адрес возврата с параметрами. Разрешённые адреса строки запроса не имеют."""
    заданные = {ключ: значение for ключ, значение in params.items() if значение is not None}
    return f"{uri}?{urlencode(заданные)}"


@dataclass(frozen=True)
class Ask:
    """Разобранный запрос авторизации: что и куда, уже проверенное."""

    client: oauth_store.Client
    redirect_uri: str
    state: str | None
    code_challenge: str
    #: Адрес MCP (RFC 8707): названный клиентом и сверенный или подставленный.
    resource: str


def _json_error(status: int, error: str, description: str, retry_after: int = 0) -> Response:
    ответ = jsonify({"error": error, "error_description": description})
    ответ.status_code = status
    ответ.headers.update(_JSON_NO_STORE)
    if retry_after > 0:
        ответ.headers["Retry-After"] = str(retry_after)
    return ответ


def _counted_failure(address: str, status: int, error: str, description: str) -> Response:
    """Отказ, засчитанный адресу. Запертому адресу — 429 без новой отметки.

    Счётчик — тот же, что у формы входа и API (`auth.throttle_tenant`): подбор
    кода и подбор пароля с одного адреса — один перебор. Удача проходит и с
    запертого адреса, как у API (`swarm_api._identify`): адрес сервера Claude
    общий у всех, и чужие неудачи не должны отнимать у человека подключение.
    Импорт здесь, а не вверху: `auth` сам импортирует этот модуль ради `ENDPOINTS`.
    """
    from .auth import throttle_tenant

    рубеж = throttle_tenant()
    запрет = web_throttle.address_verdict(tenant=рубеж, address=address)
    if запрет.locked:
        return _json_error(429, "slow_down", "too many failed attempts", запрет.retry_after_seconds)
    web_throttle.note_address_failure(tenant=рубеж, address=address)
    return _json_error(status, error, description)


def registration_full(address: str) -> bool:
    """Предел регистраций выбран: адресом или всеми вместе. Сначала свой — он дешевле и чаще."""
    if (
        oauth_store.recent_clients(REGISTRATION_WINDOW, address=address)
        >= REGISTRATIONS_PER_ADDRESS
    ):
        return True
    return oauth_store.recent_clients(REGISTRATION_WINDOW) >= REGISTRATIONS_PER_WINDOW


def _purge_after_issue() -> None:
    """Чистка после выдачи токенов: так истёкшие токены не копятся и без новых регистраций.

    Отдельной транзакцией и после выдачи: сбой чистки не отнимает у человека
    выданную пару, а пишется в журнал — молча он не проходит.
    """
    try:
        oauth_store.purge_stale()
    except AccessError:
        logger.warning("чистка OAuth не прошла — отжившие коды и токены остались", exc_info=True)


def _registration_uris(body: object) -> list[str] | None:
    """Адреса возврата из тела регистрации — или `None`, если хоть один не из разрешённых."""
    if not isinstance(body, dict):
        return None
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 0 < len(uris) <= oauth_store.MAX_REDIRECT_URIS:
        return None
    if not all(oauth_store.redirect_uri_allowed(uri) for uri in uris):
        return None
    return [str(uri) for uri in uris]


def _client_id_of_request() -> str:
    """`client_id` из тела или, если клиент прислал его так, из HTTP Basic."""
    из_тела = request.form.get("client_id") or ""
    if из_тела:
        return из_тела
    basic = request.authorization
    return (basic.username or "") if basic is not None and basic.type == "basic" else ""


def install(app: Flask, conf: Settings) -> None:
    """Маршруты OAuth — только при заданных публичных адресах (D417)."""
    if not conf.oauth_enabled:
        return
    issuer = conf.admin_public_url or ""
    mcp_url = conf.mcp_public_url or ""

    def refused_page(причина: str) -> tuple[str, int]:
        """Отказ без редиректа: клиент или адрес возврата не опознаны — уводить некуда."""
        return render_template("oauth/refused.html", reason=причина), 400

    def ask_of(params: MultiDict[str, str]) -> Ask | Response | tuple[str, int]:
        """Проверить запрос авторизации. Порядок важен: сперва клиент и адрес возврата.

        Пока они не подтверждены, отказ — страница, а не редирект: иначе
        подложенный `redirect_uri` получал бы ответы сервера на чужой адрес.
        """
        client_id = params.get("client_id") or ""
        client = oauth_store.find_client(client_id) if client_id else None
        if client is None:
            return refused_page("unknown_client")
        один = client.redirect_uris[0] if len(client.redirect_uris) == 1 else ""
        redirect_uri = params.get("redirect_uri") or один
        if redirect_uri not in client.redirect_uris or not oauth_store.redirect_uri_allowed(
            redirect_uri
        ):
            return refused_page("bad_redirect")
        state = params.get("state")

        def назад(error: str) -> Response:
            return redirect(with_query(redirect_uri, error=error, state=state, iss=issuer))

        if params.get("response_type") != "code":
            return назад("unsupported_response_type")
        challenge = params.get("code_challenge")
        if params.get("code_challenge_method") != "S256" or not oauth_store.challenge_valid(
            challenge
        ):
            return назад("invalid_request")
        resource = (params.get("resource") or mcp_url).rstrip("/")
        if resource != mcp_url:
            return назад("invalid_target")
        return Ask(
            client=client,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=str(challenge),
            resource=resource,
        )

    @app.get(AUTHORIZATION_SERVER_PATH, endpoint="oauth_metadata")
    def oauth_metadata() -> Response:
        return jsonify(metadata(issuer))

    @app.post(REGISTER_PATH, endpoint="oauth_register")
    def oauth_register() -> Response:
        """DCR: адреса возврата — только Claude. Способ входа клиента всегда `none`.

        Запрошенные `token_endpoint_auth_method`, `grant_types` и
        `response_types` не отвергаются, а заменяются своими (RFC 7591 §3.2.1
        разрешает серверу отвечать иными значениями): клиент, попросивший
        лишнего, получает ровно то, что здесь есть, и подключается.
        """
        адрес = client_address(trusted_proxies=conf.trusted_proxies)
        тело = request.get_json(silent=True)
        uris = _registration_uris(тело)
        if uris is None:
            return _counted_failure(
                адрес,
                400,
                "invalid_redirect_uri",
                "redirect_uris must be Claude callback addresses",
            )
        имя = тело.get("client_name") if isinstance(тело, dict) else None
        try:
            oauth_store.purge_stale()
            if registration_full(адрес):
                return _json_error(
                    429,
                    "temporarily_unavailable",
                    "registration limit reached",
                    int(REGISTRATION_WINDOW.total_seconds()),
                )
            клиент = oauth_store.register_client(имя, uris, address=адрес)
        except AccessError:
            return _json_error(503, "temporarily_unavailable", "storage unavailable")
        ответ = jsonify(
            {
                "client_id": клиент.client_id,
                "client_name": клиент.client_name,
                "redirect_uris": list(клиент.redirect_uris),
                "grant_types": list(GRANT_TYPES),
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": oauth_store.SCOPE,
            }
        )
        ответ.status_code = 201
        ответ.headers.update(_JSON_NO_STORE)
        return ответ

    @app.route(AUTHORIZE_PATH, methods=("GET", "POST"), endpoint=AUTHORIZE_ENDPOINT)
    def oauth_authorize() -> Response | str | tuple[str, int]:
        """Согласие вошедшего. GET — страница, POST — «Разрешить» или «Отказать»."""
        from .auth import current_account

        if request.method == "POST":
            refuse_foreign_origin()
        запрос = ask_of(request.form if request.method == "POST" else request.args)
        if not isinstance(запрос, Ask):
            return запрос
        account = current_account()
        if account is None:
            # Заслон входа сюда неопознанного не пускает; на случай, если
            # маршрут однажды окажется открытым, — отказ, а не код без человека.
            return refused_page("no_account")
        if request.method == "GET":
            return render_template(
                "oauth/consent.html",
                ask=запрос,
                host=urlsplit(запрос.redirect_uri).netloc,
                loopback=oauth_store.is_loopback(запрос.redirect_uri),
                login=account.login,
            )
        if request.form.get("decision") != "allow":
            return redirect(
                with_query(
                    запрос.redirect_uri, error="access_denied", state=запрос.state, iss=issuer
                )
            )
        код = oauth_store.issue_code(
            запрос.client,
            user_id=account.id,
            redirect_uri=запрос.redirect_uri,
            code_challenge=запрос.code_challenge,
            resource=запрос.resource,
        )
        return redirect(with_query(запрос.redirect_uri, code=код, state=запрос.state, iss=issuer))

    @app.post(TOKEN_PATH, endpoint="oauth_token")
    def oauth_token() -> Response:
        """Выдача токенов. Отказы — коды RFC 6749 §5.2, ответ не кэшируется."""
        адрес = client_address(trusted_proxies=conf.trusted_proxies)
        форма = request.form
        grant_type = форма.get("grant_type") or ""
        resource = форма.get("resource") or None
        client_id = _client_id_of_request()
        if grant_type not in GRANT_TYPES:
            return _json_error(400, "unsupported_grant_type", "authorization_code or refresh_token")
        try:
            if not client_id or oauth_store.find_client(client_id) is None:
                return _counted_failure(адрес, 401, "invalid_client", "unknown client_id")
            if grant_type == "authorization_code":
                code = форма.get("code") or ""
                verifier = форма.get("code_verifier") or ""
                redirect_uri = форма.get("redirect_uri") or ""
                if not code or not verifier or not redirect_uri:
                    return _json_error(
                        400, "invalid_request", "code, code_verifier and redirect_uri required"
                    )
                пара = oauth_store.exchange_code(
                    code,
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    verifier=verifier,
                    resource=resource,
                )
            else:
                refresh = форма.get("refresh_token") or ""
                if not refresh:
                    return _json_error(400, "invalid_request", "refresh_token required")
                пара = oauth_store.refresh_tokens(refresh, client_id=client_id, resource=resource)
        except OAuthGrantError as отказ:
            return _counted_failure(адрес, 400, отказ.error, str(отказ))
        except AccessError:
            return _json_error(503, "temporarily_unavailable", "storage unavailable")
        _purge_after_issue()
        ответ = jsonify(
            {
                "access_token": пара.access_token,
                "token_type": "Bearer",
                "expires_in": пара.expires_in,
                "refresh_token": пара.refresh_token,
                "scope": oauth_store.SCOPE,
            }
        )
        ответ.headers.update(_JSON_NO_STORE)
        return ответ
