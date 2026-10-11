"""API чтения для Swarm, v1 (#567, D387, D390): рейтинги, нарушения, проверки, карты.

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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flask import Flask, Response, jsonify, request

from src.db import api_access, maps_store, queries, ratings_read, swarm_read, web_throttle
from src.db.errors import DbError
from src.db.reach import Reach
from src.domain.tenants import HQ_TENANT
from src.ratings import feed, maps
from src.ratings.model import RKO, RS

from . import inspection_titles
from .config import Settings
from .remote import client_address
from .sections import section

PREFIX = "/api/v1"
SCORES_PATH = f"{PREFIX}/ratings/scores"
CHECKUPS_PATH = f"{PREFIX}/ratings/checkups"
VIOLATIONS_PATH = f"{PREFIX}/ratings/violations"
INSPECTIONS_PATH = f"{PREFIX}/inspections"
INSPECTION_PATH = f"{PREFIX}/inspections/<inspection_id>"
MAPS_PATH = f"{PREFIX}/maps/ratings"

SCORES_ENDPOINT = "swarm_api_scores"
CHECKUPS_ENDPOINT = "swarm_api_checkups"
VIOLATIONS_ENDPOINT = "swarm_api_violations"
INSPECTIONS_ENDPOINT = "swarm_api_inspections"
INSPECTION_ENDPOINT = "swarm_api_inspection"
MAPS_ENDPOINT = "swarm_api_maps"
#: Открыты заслону входа (`auth.OPEN_ENDPOINTS`): опознаёт токен, а не кука.
ENDPOINTS = frozenset(
    {
        SCORES_ENDPOINT,
        CHECKUPS_ENDPOINT,
        VIOLATIONS_ENDPOINT,
        INSPECTIONS_ENDPOINT,
        INSPECTION_ENDPOINT,
        MAPS_ENDPOINT,
    }
)

#: Код отказа запертому адресу: перебор токена с него уже записан счётчиком.
LOCKED = "locked"

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

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
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

    Порядок намеренный: сначала сверка токена, потом запрет адреса. Верный
    токен проходит и с запертого адреса: Swarm ходит из Edge Functions, чьи
    исходящие адреса делят с ним чужие клиенты Supabase, и посторонний, набрав
    20 неудач с того же адреса, иначе запер бы его на час. Перебор от этого не
    дешевеет: неверный токен с запертого адреса отбивается 429 без новой
    отметки, а сверка отпечатка — один запрос по уникальному индексу.

    Счётчик — тот же, что у формы входа (`auth.throttle_tenant`): подбор токена
    и подбор пароля с одного адреса — один перебор. Импорт здесь, а не вверху:
    `auth` сам импортирует этот модуль ради `ENDPOINTS`.
    """
    from .auth import throttle_tenant

    предъявлен = _bearer()
    токен = api_access.resolve(предъявлен) if предъявлен else None
    if токен is not None:
        return токен
    рубеж = throttle_tenant()
    запрет = web_throttle.address_verdict(tenant=рубеж, address=address)
    if запрет.locked:
        raise ApiRefusal(429, LOCKED, "too many failed attempts", запрет.retry_after_seconds)
    web_throttle.note_address_failure(tenant=рубеж, address=address)
    if предъявлен is None:
        raise ApiRefusal(401, "unauthorized", "Authorization: Bearer <token> required")
    raise ApiRefusal(401, "unauthorized", "invalid token")


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
    return periods, _countries_or_imf(query.countries)


def _countries_or_imf(countries: tuple[str, ...] | None) -> list[str]:
    """Названные страны или, без фильтра, все страны IMF."""
    if countries is not None:
        return list(countries)
    return [c.code for c in ratings_read.countries() if c.is_imf]


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


def _inspection_json(row: swarm_read.InspectionRow) -> dict[str, Any]:
    """Запись проверки — одна форма в списке и в деталях. Без ПД: ни аудитора,
    ни партнёра, ни контакта, ни чата (D391)."""
    prev = row.previous
    return {
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
        "path": f"{section('registry').path}/{row.id}",
        "previous": (
            {
                "id": prev.id,
                "date": prev.inspection_date.isoformat(),
                "score_pct": prev.pct,
                "grade": prev.grade,
            }
            if prev
            else None
        ),
    }


def _network() -> Reach:
    """Охват API: вся сеть УК, страны — фильтр запроса (D387)."""
    return Reach(tenant=HQ_TENANT, tenants=None, countries=None)


def _inspections(_: Settings) -> dict[str, Any]:
    query = _query()
    limit = _int("limit", DEFAULT_INSPECTIONS, swarm_read.MAX_INSPECTIONS)
    reach = Reach(tenant=HQ_TENANT, tenants=None, countries=query.countries)
    # На одну больше предела: так видно, что выдача обрезана, без второго запроса.
    rows = swarm_read.inspections(
        reach=reach, date_from=query.date_from, date_to=query.date_to, limit=limit + 1
    )
    return {
        "inspections": [_inspection_json(row) for row in rows[:limit]],
        "truncated": len(rows) > limit,
    }


def _inspection(_: Settings) -> dict[str, Any]:
    """Одна принятая проверка с разбивкой и записями (D391). Только формулировка
    записи (`text`, факт по правилам фиксации); комментарий и сырые слова
    аудитора, кадры, шапка с аудитором и партнёром наружу не идут."""
    ident = str((request.view_args or {}).get("inspection_id", ""))
    if not _UUID.fullmatch(ident):
        raise ApiRefusal(400, "bad_id", "inspection id: UUID expected")
    ident = ident.lower()
    row = swarm_read.inspection(reach=_network(), inspection_id=ident)
    detail = queries.get_inspection(ident, reach=_network()) if row else None
    if row is None or detail is None:
        raise ApiRefusal(404, "not_found", "no such finalized inspection")
    titles = inspection_titles.item_titles(detail.inspection.checklist_version)
    return {
        "inspection": {
            **_inspection_json(row),
            "deductions": detail.deductions,
            "counts": detail.counts,
            "zones": [
                {
                    "zone": str(zone.get("code", code)),
                    "title_ru": zone.get("name_ru"),
                    "title_en": zone.get("name_en"),
                    "share": zone.get("share"),
                    "loss": zone.get("loss"),
                    "left": zone.get("left"),
                    "zeroed": bool(zone.get("zeroed", False)),
                }
                for code, zone in sorted(detail.by_zone.items())
            ],
        },
        "findings": [
            {
                "n": f.n,
                "code": f.code,
                "title_ru": titles.get(f.code.strip().upper(), (None, None))[0],
                "title_en": titles.get(f.code.strip().upper(), (None, None))[1],
                "level": f.level,
                "zone": f.zone,
                "text": f.text,
                "repeat": f.repeat,
            }
            for f in sorted(detail.findings, key=lambda f: f.n)
        ],
    }


def _maps(_: Settings) -> dict[str, Any]:
    """Оценки на картах (D390): средние стран как на «Рейтингах» и пиццерии."""
    countries = _countries_or_imf(_countries())
    on = _day("on") or datetime.now(UTC).date()
    compare = _day("compare")
    if compare is not None and compare >= on:
        raise ApiRefusal(400, "bad_range", "compare must be earlier than on")
    current = maps.summarize(maps_store.latest(countries, until=on), countries)
    if compare is not None:
        current = maps.with_delta(
            current, maps.summarize(maps_store.latest(countries, until=compare), countries)
        )
    before = swarm_read.map_units(countries=countries, on=compare) if compare else None
    return {
        "on": on.isoformat(),
        "compare": compare.isoformat() if compare else None,
        "providers": feed.map_providers(),
        "countries": feed.map_countries(current),
        "units": feed.map_units(swarm_read.map_units(countries=countries, on=on), before),
        "loaded_at": feed.iso_utc(maps_store.last_ok_load()),
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
    if статус == 429 and токен_id is None:
        # Отказ запертому адресу в журнал не идёт: перебор с него не должен
        # раздувать `api.access_log`. Неудачи до запрета записаны поштучно.
        return ответ, статус
    try:
        api_access.log_access(
            токен_id, request.path, статус, client_address(trusted_proxies=conf.trusted_proxies)
        )
    except DbError:
        return _error(503, "db_unavailable", "database did not answer; retry later")
    return ответ, статус


def install(app: Flask, conf: Settings) -> None:
    """Повесить адреса API. Только GET (и HEAD, который Flask даёт сам)."""
    маршруты = (
        (SCORES_PATH, SCORES_ENDPOINT, api_access.SCOPE_RATINGS_READ, _scores),
        (CHECKUPS_PATH, CHECKUPS_ENDPOINT, api_access.SCOPE_RATINGS_READ, _checkups),
        (VIOLATIONS_PATH, VIOLATIONS_ENDPOINT, api_access.SCOPE_RATINGS_READ, _violations),
        (INSPECTIONS_PATH, INSPECTIONS_ENDPOINT, api_access.SCOPE_INSPECTIONS_READ, _inspections),
        (INSPECTION_PATH, INSPECTION_ENDPOINT, api_access.SCOPE_INSPECTIONS_READ, _inspection),
        (MAPS_PATH, MAPS_ENDPOINT, api_access.SCOPE_RATINGS_READ, _maps),
    )
    for путь, имя, право, build in маршруты:
        app.add_url_rule(
            путь,
            endpoint=имя,
            # Аргументы адреса (`<inspection_id>`) build читает из `request.view_args`.
            view_func=lambda право=право, build=build, **_: _serve(conf, право, build),
            methods=("GET",),
        )
