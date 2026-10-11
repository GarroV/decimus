"""API чтения для Swarm, v1 (#567, D387): рейтинги, собираемость, нарушения, проверки.

Децимус — единственный источник этих данных; Swarm их не хранит и не грузит у
себя, а забирает отсюда с сервера (Edge Function), не из браузера. Контракт —
`docs/12-web-admin.md`, раздел «API чтения для Swarm».

**Опознание — сервисный токен, а не учётка** (D356, D388). Адреса открыты
заслону входа (`auth.OPEN_ENDPOINTS`), как мини-апп обхода, и опознаются здесь
же: `Authorization: Bearer <токен>`. Токен ищется по отпечатку SHA-256 в
`api.tokens` (`src/db/api_access.py`, миграция `0049`); значение нигде не
хранится. В остальном приложении токен ничего не значит — заслон входа
смотрит на куку, а не на заголовок.

- неизвестный или отозванный токен — 401 и неудача в счётчике адреса (тот же,
  что у формы входа, `web_throttle`); адрес заперт — 429 с `Retry-After`;
- у токена нет права маршрута (`ratings:read` — баллы, собираемость,
  нарушения; `inspections:read` — проверки) — 403;
- больше `RATE_LIMIT_PER_MINUTE` обращений токеном за минуту — 429;
- каждое обращение, включая отказы, пишется в `api.access_log`; не удалось
  записать или сверить — 503, а не открытый доступ.

**Доступ по странам решает Swarm** (D387): API отдаёт то, что попросили, по
всей сети, как УК. Персональных данных в ответах нет — ни аудиторов, ни почт,
ни кадров.

Тексты ошибок — для разработчика на той стороне, по-английски; это не
пользовательская поверхность.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from flask import Flask, Response, jsonify, request

from src.db import api_access, ratings_read, swarm_read, web_throttle
from src.db.errors import DbError
from src.db.reach import Reach
from src.domain.tenants import HQ_TENANT
from src.ratings import feed
from src.ratings.model import RKO, RS

from .config import Settings
from .remote import client_address
from .sections import section

PREFIX = "/api/v1"
SCORES_PATH = f"{PREFIX}/ratings/scores"
CHECKUPS_PATH = f"{PREFIX}/ratings/checkups"
VIOLATIONS_PATH = f"{PREFIX}/ratings/violations"
INSPECTIONS_PATH = f"{PREFIX}/inspections"

SCORES_ENDPOINT = "swarm_api_scores"
CHECKUPS_ENDPOINT = "swarm_api_checkups"
VIOLATIONS_ENDPOINT = "swarm_api_violations"
INSPECTIONS_ENDPOINT = "swarm_api_inspections"
#: Открыты заслону входа (`auth.OPEN_ENDPOINTS`): опознаёт токен, а не кука.
ENDPOINTS = frozenset(
    {SCORES_ENDPOINT, CHECKUPS_ENDPOINT, VIOLATIONS_ENDPOINT, INSPECTIONS_ENDPOINT}
)

RATING_TYPES = (RS, RKO)
#: Сколько стран можно назвать в одном запросе — с запасом на всю сеть.
MAX_COUNTRIES = 50
#: Больше периодов за запрос не отдаётся: пять лет недель РКО. Дальше — сужать даты.
MAX_PERIODS = 260
DEFAULT_TOP = 5
MAX_TOP = 20
DEFAULT_INSPECTIONS = 500
#: Кэш на той стороне: данные обновляются загрузкой раз в неделю-две.
CACHE_CONTROL = "private, max-age=300"
#: Обращений одним токеном за минуту. Swarm кэширует ответы на пять минут и
#: ходит единицами запросов; сотня с лишним в минуту — это уже не он.
RATE_LIMIT_PER_MINUTE = 120
RATE_WINDOW = timedelta(minutes=1)

_COUNTRY = re.compile(r"[A-Z]{2}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class ApiRefusal(Exception):
    """Отказ запроса: код ошибки, текст для разработчика, HTTP-статус.

    `retry_after` (секунды) больше нуля — ответ несёт заголовок `Retry-After`.
    """

    def __init__(self, status: int, code: str, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after


@dataclass(frozen=True)
class Query:
    countries: tuple[str, ...] | None
    date_from: date | None
    date_to: date | None


def _error(status: int, code: str, message: str, retry_after: int = 0) -> tuple[Response, int]:
    ответ = jsonify({"error": code, "message": message})
    ответ.headers["Cache-Control"] = "no-store"
    if retry_after > 0:
        ответ.headers["Retry-After"] = str(retry_after)
    if status == 401:
        ответ.headers["WWW-Authenticate"] = 'Bearer realm="decimus-api"'
    return ответ, status


def _bearer() -> str | None:
    схема, _, токен = (request.headers.get("Authorization") or "").partition(" ")
    if схема.lower() != "bearer" or not токен.strip():
        return None
    return токен.strip()


def _identify(address: str) -> api_access.ApiToken:
    """Опознать токен. Отказ — `ApiRefusal`.

    Порядок намеренный: запертый адрес отбивается до сверки токена (перебор
    обязан дешеветь), неудача записывается до ответа 401.

    Счётчик — тот же, что у формы входа (`auth.throttle_tenant`): подбор токена
    и подбор пароля с одного адреса — один перебор. Импорт здесь, а не вверху:
    `auth` сам импортирует этот модуль ради `ENDPOINTS`.
    """
    from .auth import throttle_tenant

    рубеж = throttle_tenant()
    запрет = web_throttle.address_verdict(tenant=рубеж, address=address)
    if запрет.locked:
        raise ApiRefusal(429, "locked", "too many failed attempts", запрет.retry_after_seconds)
    предъявлен = _bearer()
    токен = api_access.resolve(предъявлен) if предъявлен else None
    if токен is None:
        web_throttle.note_address_failure(tenant=рубеж, address=address)
        if предъявлен is None:
            raise ApiRefusal(401, "unauthorized", "Authorization: Bearer <token> required")
        raise ApiRefusal(401, "unauthorized", "invalid token")
    return токен


def _authorize(токен: api_access.ApiToken, scope: str) -> None:
    """Право маршрута и лимит частоты для уже опознанного токена."""
    if not токен.allows(scope):
        raise ApiRefusal(403, "forbidden", f"token lacks scope {scope}")
    if api_access.recent_requests(токен.id, RATE_WINDOW) >= RATE_LIMIT_PER_MINUTE:
        raise ApiRefusal(
            429, "rate_limited", f"at most {RATE_LIMIT_PER_MINUTE} requests per minute", 60
        )


def _day(name: str) -> date | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    if not _DAY.fullmatch(raw):
        raise ApiRefusal(400, "bad_date", f"{name}: expected YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiRefusal(400, "bad_date", f"{name}: no such date") from None


def _countries() -> tuple[str, ...] | None:
    raw = request.args.get("countries")
    if raw is None or not raw.strip():
        return None
    коды = [часть.strip().upper() for часть in raw.split(",")]
    if any(not _COUNTRY.fullmatch(код) for код in коды):
        raise ApiRefusal(400, "bad_countries", "countries: comma-separated ISO-2 codes")
    if len(коды) > MAX_COUNTRIES:
        raise ApiRefusal(400, "bad_countries", f"countries: at most {MAX_COUNTRIES} codes")
    return tuple(dict.fromkeys(коды))


def _query() -> Query:
    query = Query(_countries(), _day("from"), _day("to"))
    if query.date_from and query.date_to and query.date_from > query.date_to:
        raise ApiRefusal(400, "bad_range", "from is later than to")
    return query


def _rating_type() -> str:
    value = (request.args.get("type") or "").strip().lower()
    if value not in RATING_TYPES:
        raise ApiRefusal(400, "bad_type", "type: rs or rko")
    return value


def _int(name: str, default: int, upper: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or not 1 <= int(raw) <= upper:
        raise ApiRefusal(400, f"bad_{name}", f"{name}: integer from 1 to {upper}")
    return int(raw)


def _rating_scope(query: Query, rating_type: str) -> tuple[list[swarm_read.PeriodRow], list[str]]:
    """Периоды типа в датах запроса и страны: названные или все страны IMF."""
    periods = swarm_read.periods(rating_type, date_from=query.date_from, date_to=query.date_to)
    if len(periods) > MAX_PERIODS:
        raise ApiRefusal(
            400, "range_too_large", f"{len(periods)} periods match; narrow from/to to {MAX_PERIODS}"
        )
    if query.countries is not None:
        return periods, list(query.countries)
    return periods, [c.code for c in ratings_read.countries() if c.is_imf]


def _scores(_: Settings) -> dict[str, Any]:
    rating_type = _rating_type()
    periods, countries = _rating_scope(_query(), rating_type)
    ids = [p.id for p in periods]
    rows = swarm_read.scores(rating_type, countries=countries, period_ids=ids) if ids else []
    return {
        "type": rating_type,
        "periods": [feed.period_json(p) for p in periods],
        "units": feed.scores(ids, rows),
        "loaded_at": feed.iso_utc(swarm_read.loaded_at(feed.SCORE_FORMATS)),
    }


def _checkups(_: Settings) -> dict[str, Any]:
    rating_type = _rating_type()
    periods, countries = _rating_scope(_query(), rating_type)
    ids = [p.id for p in periods]
    by_channel, rated = (
        swarm_read.checkup_counts(rating_type, countries=countries, period_ids=ids)
        if ids
        else ([], [])
    )
    return {
        "type": rating_type,
        "periods": [feed.period_json(p) for p in periods],
        "units": feed.checkups(ids, by_channel, rated),
        "loaded_at": feed.iso_utc(swarm_read.loaded_at(feed.CHECKUP_FORMATS[rating_type])),
    }


def _violations(_: Settings) -> dict[str, Any]:
    rating_type = _rating_type()
    top = _int("top", DEFAULT_TOP, MAX_TOP)
    periods, countries = _rating_scope(_query(), rating_type)
    ids = [p.id for p in periods]
    facts, counts = (
        swarm_read.violation_facts(rating_type, countries=countries, period_ids=ids)
        if ids
        else ([], [])
    )
    return {
        "type": rating_type,
        "periods": [feed.period_json(p) for p in periods],
        "countries": feed.violations(ids, facts, counts, top=top),
        "loaded_at": feed.iso_utc(swarm_read.loaded_at(feed.VIOLATION_FORMATS[rating_type])),
    }


def _inspections(_: Settings) -> dict[str, Any]:
    query = _query()
    limit = _int("limit", DEFAULT_INSPECTIONS, swarm_read.MAX_INSPECTIONS)
    reach = Reach(tenant=HQ_TENANT, tenants=None, countries=query.countries)
    # На одну больше предела: так видно, что выдача обрезана, без второго запроса.
    rows = swarm_read.inspections(
        reach=reach, date_from=query.date_from, date_to=query.date_to, limit=limit + 1
    )
    card = section("registry").path
    return {
        "inspections": [
            {
                "id": row.id,
                "unit": {
                    "id": row.unit_id,
                    "dodo_id": row.unit_dodo_id,
                    "name": row.unit_name,
                    "cc": row.country,
                },
                "date": row.inspection_date.isoformat(),
                "kind": row.kind,
                "score_pct": row.pct,
                "grade": row.grade,
                "path": f"{card}/{row.id}",
            }
            for row in rows[:limit]
        ],
        "truncated": len(rows) > limit,
    }


def _respond(
    conf: Settings, scope: str, build: Callable[[Settings], dict[str, Any]]
) -> tuple[Response, int, int | None]:
    """Ответ на запрос и номер токена для журнала (`None` — не опознан)."""
    адрес = client_address(trusted_proxies=conf.trusted_proxies)
    токен_id: int | None = None
    try:
        токен = _identify(адрес)
        токен_id = токен.id
        _authorize(токен, scope)
        payload = build(conf)
    except ApiRefusal as refusal:
        return (
            *_error(refusal.status, refusal.code, refusal.message, refusal.retry_after),
            токен_id,
        )
    except DbError:
        return (*_error(503, "db_unavailable", "database did not answer; retry later"), токен_id)
    ответ = jsonify(payload)
    ответ.headers["Cache-Control"] = CACHE_CONTROL
    ответ.headers["Vary"] = "Authorization"
    return ответ, 200, токен_id


def _serve(
    conf: Settings, scope: str, build: Callable[[Settings], dict[str, Any]]
) -> tuple[Response, int]:
    """Ответить и записать обращение в журнал. Не записалось — 503, а не ответ без следа."""
    ответ, статус, токен_id = _respond(conf, scope, build)
    try:
        api_access.log_access(
            токен_id, request.path, статус, client_address(trusted_proxies=conf.trusted_proxies)
        )
    except DbError:
        return _error(503, "db_unavailable", "database did not answer; retry later")
    return ответ, статус


def install(app: Flask, conf: Settings) -> None:
    """Повесить четыре адреса API. Только GET (и HEAD, который Flask даёт сам)."""
    маршруты = (
        (SCORES_PATH, SCORES_ENDPOINT, api_access.SCOPE_RATINGS_READ, _scores),
        (CHECKUPS_PATH, CHECKUPS_ENDPOINT, api_access.SCOPE_RATINGS_READ, _checkups),
        (VIOLATIONS_PATH, VIOLATIONS_ENDPOINT, api_access.SCOPE_RATINGS_READ, _violations),
        (INSPECTIONS_PATH, INSPECTIONS_ENDPOINT, api_access.SCOPE_INSPECTIONS_READ, _inspections),
    )
    for путь, имя, право, build in маршруты:
        app.add_url_rule(
            путь,
            endpoint=имя,
            view_func=lambda право=право, build=build: _serve(conf, право, build),
            methods=("GET",),
        )
