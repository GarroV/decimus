"""API чтения `/api/v1` для сервисов по токену (#567, #568, D336).

Четыре маршрута только на чтение: баллы рейтингов, собираемость, топ
нарушений и итоги выездных проверок. Потребитель — сервер Swarm (Edge
Function), не браузер: CORS не включается, кука админки не читается.

**Две двери не открывают друг друга.** Маршруты API стоят в
`auth.OPEN_ENDPOINTS`, поэтому заслон входа админки их пропускает, а свой
заслон здесь смотрит ТОЛЬКО на `Authorization: Bearer`: кука сессии к API
доступа не даёт. И наоборот: заслон админки заголовок `Authorization` не
читает вовсе, поэтому токен не открывает ни одного экрана.

**Порядок заслона** (`_guard`): адрес не заперт за неудачи → токен есть, похож
на выпущенный и живой в базе (иначе 401, один текст на «нет такого» и
«отозван») → потолок частоты токена (429) → право маршрута (403). Значение
токена и заголовок `Authorization` не попадают ни в журнал, ни в ответ.

Выключено по умолчанию: без `API_ENABLED=1` маршрутов нет (`install`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any

from flask import Flask, Response, g, request, url_for

from src.db import api_inspections, api_tokens
from src.db import ratings_read as ratings_db
from src.db.api_tokens import SCOPE_INSPECTIONS_READ, SCOPE_RATINGS_READ, ApiConsumer
from src.db.errors import DbError
from src.ratings import api_payload
from src.ratings.countries import EXCLUDED, NAMES

from . import api_limits
from .config import Settings
from .remote import client_address

logger = logging.getLogger(__name__)

PREFIX = "/api/v1"

EP_SCORES = "api_v1_ratings_scores"
EP_CHECKUPS = "api_v1_ratings_checkups"
EP_VIOLATIONS = "api_v1_ratings_violations"
EP_INSPECTIONS = "api_v1_inspections"
#: Всё прочее под `/api/v1` — 404 в JSON, но только ПОСЛЕ проверки токена:
#: без токена карта API наружу не отвечает ничем, кроме 401.
EP_OTHER = "api_v1_other"

ENDPOINTS = frozenset({EP_SCORES, EP_CHECKUPS, EP_VIOLATIONS, EP_INSPECTIONS, EP_OTHER})

_SCOPE_OF: Mapping[str, str] = {
    EP_SCORES: SCOPE_RATINGS_READ,
    EP_CHECKUPS: SCOPE_RATINGS_READ,
    EP_VIOLATIONS: SCOPE_RATINGS_READ,
    EP_INSPECTIONS: SCOPE_INSPECTIONS_READ,
}

#: Страны охвата IMF из справочника сети (D318): допустимые значения `countries`.
IMF_COUNTRIES = tuple(sorted(code for code in NAMES if code not in EXCLUDED))

RATING_TYPES = ("rs", "rko")
TOP_DEFAULT = 5
TOP_MAX = 20
MAX_COUNTRIES = len(IMF_COUNTRIES)
#: Предел строк `/inspections` в одном ответе; больше — 400, сузить даты.
MAX_INSPECTIONS = 5000
CACHE_OK = "private, max-age=300"

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_COUNTRY = re.compile(r"[A-Z]{2}")
_PARAMS_RATINGS = frozenset({"type", "countries", "from", "to"})
_PARAMS_VIOLATIONS = _PARAMS_RATINGS | {"top"}
_PARAMS_INSPECTIONS = frozenset({"countries", "from", "to"})
_PARAMS_LOGGED = _PARAMS_VIOLATIONS
#: Сколько знаков параметра и пути попадает в журнал: снаружи присылают что угодно.
_LOG_CLIP = 120

_CONSUMER = "api_consumer"
_STARTED = "api_started"


class ApiRefusal(Exception):
    """Отказ запроса кодом контракта: `{error, message}` с HTTP-статусом."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message


def _json(payload: object, status: int = 200) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        status=status,
        mimetype="application/json",
    )


def _error(status: int, code: str, message: str, *, retry_after: int | None = None) -> Response:
    ответ = _json({"error": code, "message": message}, status)
    if retry_after is not None:
        ответ.headers["Retry-After"] = str(retry_after)
    return ответ


def bearer(header: str) -> str | None:
    """Токен из `Authorization: Bearer <токен>`; другое — `None`."""
    схема, _, значение = header.strip().partition(" ")
    if схема.lower() != "bearer":
        return None
    значение = значение.strip()
    return значение or None


# --- параметры -----------------------------------------------------------------


def _single(args: Any, name: str) -> str | None:
    values = args.getlist(name)
    if len(values) > 1:
        raise ApiRefusal(400, "bad_parameter", f"Parameter '{name}' is given more than once")
    return values[0] if values else None


def _check_known(args: Any, allowed: frozenset[str]) -> None:
    unknown = sorted(set(args.keys()) - allowed)
    if unknown:
        raise ApiRefusal(
            400,
            "unknown_parameter",
            f"Unknown parameter; allowed: {', '.join(sorted(allowed))}",
        )


def parse_type(raw: str | None) -> str:
    if raw not in RATING_TYPES:
        raise ApiRefusal(400, "bad_type", "Parameter 'type' must be 'rs' or 'rko'")
    return raw


def parse_countries(raw: str) -> tuple[str, ...]:
    """Коды ISO-2 через запятую — только страны охвата IMF; повтор схлопывается."""
    codes = tuple(dict.fromkeys(part.strip().upper() for part in raw.split(",") if part.strip()))
    if not codes or len(codes) > MAX_COUNTRIES:
        raise ApiRefusal(400, "bad_countries", "Parameter 'countries' must list ISO-2 codes")
    for code in codes:
        if not _COUNTRY.fullmatch(code) or code not in IMF_COUNTRIES:
            raise ApiRefusal(
                400, "bad_countries", "Parameter 'countries' has a code outside IMF countries"
            )
    return codes


def parse_date(raw: str | None, name: str) -> date | None:
    if raw is None:
        return None
    if not _DATE.fullmatch(raw):
        raise ApiRefusal(400, "bad_date", f"Parameter '{name}' must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ApiRefusal(400, "bad_date", f"Parameter '{name}' must be YYYY-MM-DD") from exc


def parse_range(args: Any) -> tuple[date | None, date | None]:
    begin = parse_date(_single(args, "from"), "from")
    end = parse_date(_single(args, "to"), "to")
    if begin and end and begin > end:
        raise ApiRefusal(400, "bad_range", "Parameter 'from' is after 'to'")
    return begin, end


def parse_top(raw: str | None) -> int:
    if raw is None:
        return TOP_DEFAULT
    if not (raw.isascii() and raw.isdigit()) or not 1 <= int(raw) <= TOP_MAX:
        raise ApiRefusal(400, "bad_top", f"Parameter 'top' must be an integer 1..{TOP_MAX}")
    return int(raw)


def _ratings_query(args: Any, allowed: frozenset[str]) -> api_payload.Query:
    _check_known(args, allowed)
    rating_type = parse_type(_single(args, "type"))
    raw_countries = _single(args, "countries")
    countries = (
        parse_countries(raw_countries)
        if raw_countries is not None
        else _ratings_default_countries()
    )
    begin, end = parse_range(args)
    return api_payload.Query(rating_type, countries, begin, end)


def _ratings_default_countries() -> tuple[str, ...]:
    """Без `countries` — страны IMF, которые есть в справочнике рейтингов."""
    return tuple(
        sorted(
            row.code for row in ratings_db.countries() if row.is_imf and row.code not in EXCLUDED
        )
    )


# --- ответы ----------------------------------------------------------------------


def _ratings(
    build: Callable[[api_payload.Query], dict[str, Any]], allowed: frozenset[str]
) -> Response:
    query = _ratings_query(request.args, allowed)
    try:
        return _json(build(query))
    except api_payload.RangeTooLargeError as exc:
        raise ApiRefusal(
            400,
            "range_too_large",
            f"More than {api_payload.MAX_PERIODS} periods; narrow 'from'/'to'",
        ) from exc


def _inspections() -> Response:
    _check_known(request.args, _PARAMS_INSPECTIONS)
    raw_countries = _single(request.args, "countries")
    countries = IMF_COUNTRIES if raw_countries is None else parse_countries(raw_countries)
    begin, end = parse_range(request.args)
    rows = api_inspections.inspection_results(
        countries=countries, date_from=begin, date_to=end, limit=MAX_INSPECTIONS + 1
    )
    if len(rows) > MAX_INSPECTIONS:
        raise ApiRefusal(
            400, "range_too_large", f"More than {MAX_INSPECTIONS} inspections; narrow 'from'/'to'"
        )
    return _json(
        {
            "inspections": [
                {
                    "id": row.id,
                    "unit": {
                        "id": row.unit_id,
                        "dodo_id": row.unit_dodo_id,
                        "name": row.unit_name,
                        "cc": row.country,
                    },
                    "date": row.date.isoformat(),
                    "status": row.status,
                    "score_pct": float(row.pct),
                    "grade": row.grade,
                    "url": url_for("card", inspection_id=row.id, _external=True),
                }
                for row in rows
            ]
        }
    )


def _served(handler: Callable[[], Response]) -> Response:
    """Отказы — ответом контракта; база — 503; прочее — 500 без подробностей наружу."""
    try:
        return handler()
    except ApiRefusal as refusal:
        return _error(refusal.status, refusal.code, refusal.message)
    except DbError as exc:
        logger.warning("api: база отказала (%s)", type(exc).__name__)
        return _error(503, "unavailable", "Data source is temporarily unavailable")
    except Exception:
        logger.exception("api: сбой обработки %s", request.endpoint)
        return _error(500, "internal", "Internal error")


# --- журнал ----------------------------------------------------------------------


def _journal(status: int, address: str) -> None:
    """Строка журнала обращения: кто, куда, с чем, чем кончилось. Без токена."""
    consumer: ApiConsumer | None = getattr(g, _CONSUMER, None)
    started = getattr(g, _STARTED, None)
    record = {
        "event": "api_access",
        "consumer": consumer.consumer if consumer else None,
        "token_id": consumer.token_id if consumer else None,
        "method": request.method,
        "path": request.path[:_LOG_CLIP],
        "params": {
            key: request.args.get(key, "")[:_LOG_CLIP]
            for key in sorted(_PARAMS_LOGGED)
            if key in request.args
        },
        "status": status,
        "ms": None if started is None else round((time.monotonic() - started) * 1000),
        "address": address,
    }
    logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


# --- установка -----------------------------------------------------------------


def install(app: Flask, conf: Settings) -> None:
    """Зарегистрировать маршруты и заслон API. Без `API_ENABLED=1` — ничего."""
    if not conf.api_enabled:
        return
    per_token = api_limits.Window(api_limits.PER_TOKEN_PER_MINUTE)
    per_address = api_limits.Window(api_limits.FAILURES_PER_MINUTE)

    def address() -> str:
        return client_address(trusted_proxies=conf.trusted_proxies)

    @app.before_request
    def _guard() -> Response | None:
        if request.endpoint not in ENDPOINTS:
            return None
        setattr(g, _STARTED, time.monotonic())
        откуда = address()
        wait = per_address.blocked(откуда)
        if wait:
            return _error(429, "rate_limited", "Too many requests", retry_after=wait)
        token = bearer(request.headers.get("Authorization", ""))
        try:
            consumer = api_tokens.resolve(token) if token else None
        except DbError as exc:
            logger.warning("api: токен не сверен, база отказала (%s)", type(exc).__name__)
            return _error(503, "unavailable", "Data source is temporarily unavailable")
        if consumer is None:
            per_address.hit(откуда)
            return _error(401, "unauthorized", "A valid bearer token is required")
        setattr(g, _CONSUMER, consumer)
        wait = per_token.hit(consumer.token_id)
        if wait:
            return _error(429, "rate_limited", "Too many requests", retry_after=wait)
        scope = _SCOPE_OF.get(str(request.endpoint))
        if scope is not None and scope not in consumer.scopes:
            return _error(403, "forbidden", "The token does not grant this route")
        return None

    @app.after_request
    def _after(response: Response) -> Response:
        if request.endpoint not in ENDPOINTS:
            return response
        response.headers["Cache-Control"] = CACHE_OK if response.status_code == 200 else "no-store"
        response.headers["Vary"] = "Authorization"
        _journal(response.status_code, address())
        return response

    @app.get(f"{PREFIX}/ratings/scores", endpoint=EP_SCORES)
    def _scores() -> Response:
        return _served(lambda: _ratings(api_payload.scores, _PARAMS_RATINGS))

    @app.get(f"{PREFIX}/ratings/checkups", endpoint=EP_CHECKUPS)
    def _checkups() -> Response:
        return _served(lambda: _ratings(api_payload.checkups, _PARAMS_RATINGS))

    @app.get(f"{PREFIX}/ratings/violations", endpoint=EP_VIOLATIONS)
    def _violations() -> Response:
        def build(query: api_payload.Query) -> dict[str, Any]:
            return api_payload.violations(query, top=parse_top(_single(request.args, "top")))

        return _served(lambda: _ratings(build, _PARAMS_VIOLATIONS))

    @app.get(f"{PREFIX}/inspections", endpoint=EP_INSPECTIONS)
    def _inspections_route() -> Response:
        return _served(_inspections)

    @app.route(
        PREFIX,
        endpoint=EP_OTHER,
        methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
        defaults={"rest": ""},
    )
    @app.route(
        f"{PREFIX}/<path:rest>",
        endpoint=EP_OTHER,
        methods=("GET", "POST", "PUT", "PATCH", "DELETE"),
    )
    def _other(rest: str) -> Response:
        del rest
        return _error(404, "not_found", "No such route")
