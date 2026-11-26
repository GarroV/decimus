"""Bounded background collection of exact operating windows; no OAuth refresh.

Source history is queried immediately. Successful windows remain in Decimus when
the source later loses its history. The web API only reads this cache.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.db import dodois_logins as logins
from src.db import dodois_metrics_store as metrics_store
from src.db import performance as store
from src.db.errors import DbError
from src.domain import dodois as rules
from src.domain.dodois import Login
from src.domain.dodois_metrics import unit_id
from src.domain.performance import (
    Observation,
    Window,
    aggregate,
    comparison_windows,
    country_timezone,
    last_complete_day,
)

from . import client
from . import performance_parse as parse
from .metrics import _each_batch

logger = logging.getLogger(__name__)
FRESH_FOR = timedelta(hours=20)
RETRY_AFTER = timedelta(hours=1)
MAX_COUNTRIES_PER_PASS = 3
MAX_REQUESTS_PER_PASS = 180
MAX_WINDOWS_PER_COUNTRY = 6
PAGE_SIZE = 100
MAX_PAGES = 500
PAUSE_SECONDS = 0.25
PATHS = {
    "sales": "finances/sales/units",
    "delivery": "delivery/statistics",
    "cooking": "production/orders-handover-statistics",
    "stops": "production/stop-sales-channels",
    "vouchers": "delivery/vouchers",
}
PARSERS = {
    "sales": parse.sales,
    "delivery": parse.delivery,
    "cooking": parse.cooking,
    "stops": parse.stops,
    "vouchers": parse.vouchers,
}
Sleep = Callable[[float], None]


@dataclass(frozen=True)
class Outcome:
    country: str
    kind: str
    period: Window
    rows: int
    error: str | None = None


class BudgetExhausted(Exception):
    """Yield the job; the next pass resumes from persisted successful windows."""


@dataclass
class Budget:
    remaining: int = MAX_REQUESTS_PER_PASS

    def charge(self) -> None:
        if self.remaining <= 0:
            raise BudgetExhausted
        self.remaining -= 1


@dataclass
class Throttle:
    pause: Sleep
    budget: Budget

    def retry(self, seconds: float) -> None:
        self.budget.charge()
        self.pause(seconds)


def planned_windows(cutoff: date) -> list[Window]:
    """Exact MTD comparisons first, then twelve full source-history months."""
    windows = list(comparison_windows(cutoff).values())
    end = cutoff.replace(day=1) - timedelta(days=1)
    for _ in range(12):
        period = Window(end.replace(day=1), end)
        if period not in windows:
            windows.append(period)
        end = period.start - timedelta(days=1)
    return windows


def _query(period: Window) -> dict[str, str]:
    # Finances explicitly defines [from,to). Other operations use the same local
    # timestamps; the source's remaining boundary ambiguity is recorded in docs41.
    return {"from": f"{period.start}T00:00:00", "to": f"{period.end + timedelta(days=1)}T00:00:00"}


def _due(
    states: list[dict[str, Any]], kind: str, now: datetime, *, historical: bool = False
) -> bool:
    state = next((row for row in states if row["kind"] == kind), None)
    if state is None:
        return True
    tried = datetime.fromisoformat(state["attempted_at"])
    ok = datetime.fromisoformat(state["last_ok_at"]) if state["last_ok_at"] else None
    # A structurally valid partial historical answer is retained and reported as
    # partial, but must not monopolize every retry ahead of untouched history.
    if state.get("error_code") in {"incomplete_response", "no_source_data"}:
        ok = tried
    fresh = timedelta(days=30) if historical else FRESH_FOR
    return now - tried >= RETRY_AFTER and (ok is None or now - ok >= fresh)


def _error(exc: Exception) -> str:
    if isinstance(exc, client.DodoisError):
        known = {
            "unauthorized",
            "rate_limited",
            "network",
            "no_tokens",
            "no_units",
            "incomplete_response",
            "no_source_data",
        }
        return exc.kind if exc.kind in known else "source_refused"
    return "database_error" if isinstance(exc, DbError) else "source_shape"


def _get(
    login: Login, access: str, path: str, query: dict[str, str], throttle: Throttle
) -> client.Response:
    # One shared budget includes split batches, pagination and the client's 429 retry.
    throttle.budget.charge()
    throttle.pause(PAUSE_SECONDS)
    return client.api_get(login.contour, path, query, access, sleep=throttle.retry)


def _batch_rows(
    kind: str,
    login: Login,
    access: str,
    units: list[str],
    period: Window,
    timezone: str,
    throttle: Throttle,
) -> tuple[list[Observation], set[str]]:
    rows: list[Observation] = []
    granted: set[str] = set()
    path = f"/dodopizza/{login.country.lower()}/{PATHS[kind]}"

    def get(batch: list[str]) -> client.Response:
        query = {**_query(period), "units": ",".join(batch)}
        if kind == "cooking":
            query["salesChannels"] = "DineIn"
        if kind == "vouchers":
            query.update(skip="0", take=str(PAGE_SIZE))
        return _get(login, access, path, query, throttle)

    for batch, body in _each_batch(units, 30, get):
        if kind == "vouchers":
            merged = []
            for page in range(MAX_PAGES):
                if not isinstance(body, dict) or not isinstance(body.get("vouchers"), list):
                    raise ValueError("invalid vouchers page")
                merged.extend(body["vouchers"])
                if body.get("isEndOfListReached") is True:
                    body = {"vouchers": merged, "isEndOfListReached": True}
                    break
                query = {
                    **_query(period),
                    "units": ",".join(batch),
                    "skip": str((page + 1) * PAGE_SIZE),
                    "take": str(PAGE_SIZE),
                }
                response = _get(login, access, path, query, throttle)
                if response.status != 200:
                    raise client.DodoisError("source_refused")
                body = response.body
            else:
                raise ValueError("vouchers page limit")
        rows.extend(PARSERS[kind](body, login.country, period, timezone, batch))
        granted.update(batch)
    return rows, granted


def _save_kind(
    kind: str,
    login: Login,
    access: str,
    units: list[str],
    active: set[str],
    period: Window,
    timezone: str,
    throttle: Throttle,
    *,
    current: bool,
) -> int:
    rows, granted = _batch_rows(kind, login, access, units, period, timezone, throttle)
    existing = {
        (r.subject_id, r.metric): r
        for r in store.read_observations([login.country], period.start, period.end)
        if r.period == period
    }
    incomplete = granted != set(units) or any(row.reason == "missing_unit" for row in rows)
    # Completeness is relative to the explicit requested pizzeria universe, not
    # merely those which happened to answer. Keep denied/missing units visible.
    metrics = {row.metric for row in rows}
    for metric in metrics:
        metric_rows = [row for row in rows if row.metric == metric]
        country_rows = (
            [row for row in metric_rows if row.subject_id in active or row.amount is not None]
            if current
            else metric_rows
        )
        expected = len({*active, *(row.subject_id for row in country_rows)}) if current else None
        total = aggregate(country_rows, expected_units=expected)
        if total:
            if granted != set(units):
                total = replace(total, status="partial", reason="unit_access_incomplete")
            if not active:
                total = replace(total, status="partial", reason="active_units_unknown")
            if not current:
                total = replace(total, status="partial", reason="historical_cohort_unknown")
            old = existing.get((login.country, metric))
            if old is None or old.status != "complete" or total.status == "complete":
                rows.append(total)
    # An omitted unit is not a correction to zero. Preserve the last source
    # observation and its original timestamp when history becomes unavailable.
    to_write = [
        row
        for row in rows
        if row.reason != "missing_unit"
        and (
            row.amount is not None
            or row.reason == "no_orders"
            or (row.subject_id, row.metric) not in existing
        )
    ]
    count = store.upsert_observations(to_write)
    if kind == "sales":
        # Native country totals include historical/closed venues and do not
        # pretend that today's list is last year's country cohort.
        response = _get(
            login,
            access,
            f"/dodopizza/{login.country.lower()}/finances/sales/country",
            _query(period),
            throttle,
        )
        if response.status != 200 or not isinstance(response.body, dict):
            raise ValueError("invalid country sales response")
        value = response.body.get("result")
        if not isinstance(value, dict):
            raise ValueError("invalid country sales result")
        adapted = {"result": [{**value, "unitId": units[0]}]}
        country_rows = [
            replace(
                row,
                subject_id=login.country,
                covered_units=None,
                expected_units=None,
                source="dodois/finances/sales/country",
            )
            for row in parse.sales(adapted, login.country, period, timezone, [units[0]])
        ]
        count += store.upsert_observations(country_rows)
    if incomplete:
        # The caller records this safe code without deleting the writes above.
        raise client.DodoisError("incomplete_response")
    return count


def _save_lfl(
    login: Login,
    access: str,
    units: list[str],
    period: Window,
    granularity: str,
    throttle: Throttle,
) -> int:
    query = {
        "from": period.start.isoformat(),
        "to": period.end.isoformat(),
        "granularity": granularity,
    }
    rows = []
    granted: set[str] = set()

    def get(batch: list[str]) -> client.Response:
        return _get(
            login,
            access,
            "/customer-feedback/lfl/by-units",
            {**query, "units": ",".join(batch)},
            throttle,
        )

    for batch, body in _each_batch(units, 30, get):
        rows.extend(parse.native_lfl(body, login.country, period, granularity, batch))
        granted.update(batch)
    if granted != set(units):
        raise client.DodoisError("source_refused")
    response = _get(
        login,
        access,
        "/customer-feedback/lfl/by-countries",
        {**query, "countries": login.country.lower()},
        throttle,
    )
    if response.status != 200:
        raise client.DodoisError("source_refused")
    rows.extend(
        parse.native_lfl(
            response.body, login.country, period, granularity, [login.country], by_country=True
        )
    )
    if not rows:
        raise client.DodoisError("no_source_data")
    return store.replace_lfl(login.country, period, granularity, rows)


def collect_country(
    login: Login,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
    sleep: Sleep = time.sleep,
    budget: Budget | None = None,
) -> list[Outcome]:
    """Current/MoM/YoY history in one bounded pass, preserving prior successful values."""
    moment = now or datetime.now(UTC)
    timezone, fallback = country_timezone(login.country)
    cutoff = as_of or last_complete_day([timezone], now=moment)
    if cutoff > last_complete_day([timezone], now=moment):
        raise ValueError("incomplete or future day")
    windows = comparison_windows(cutoff)
    # Persist rotation before credential/discovery failures; one failing country
    # must never monopolize the first three scheduler slots.
    store.record_load(
        login.country, "country_attempt", windows["current"], error_code="in_progress"
    )
    budget = budget or Budget()
    throttle = Throttle(sleep, budget)
    try:
        tokens = logins.read_tokens(login.country)
        if tokens is None:
            raise client.DodoisError("no_tokens")
        budget.charge()
        active = {
            normal
            for value in client.working_pizzerias(login.country)
            if (normal := unit_id(value)) is not None
        }
        known = {
            normal
            for value in metrics_store.country_units(login.country)
            if (normal := unit_id(value)) is not None
        }
        units = sorted(active | known)
        if not units:
            raise client.DodoisError("no_units")
    except (client.DodoisError, DbError) as exc:
        store.record_load(
            login.country, "country_attempt", windows["current"], error_code=_error(exc)
        )
        return [Outcome(login.country, "country_attempt", windows["current"], 0, _error(exc))]
    outcomes: list[Outcome] = []
    processed = 0
    for period in planned_windows(cutoff):
        states = store.load_states([login.country], period)
        historical = period not in windows.values()
        kinds = list(PATHS) + (["lfl_day", "lfl_month"] if period == windows["current"] else [])
        if not any(_due(states, kind, moment, historical=historical) for kind in kinds):
            continue
        if processed >= MAX_WINDOWS_PER_COUNTRY:
            break
        processed += 1
        for kind in kinds:
            if not _due(states, kind, moment, historical=historical):
                continue
            try:
                if kind.startswith("lfl_"):
                    granularity = "Day" if kind == "lfl_day" else "Month"
                    count = _save_lfl(login, tokens.access, units, period, granularity, throttle)
                else:
                    count = _save_kind(
                        kind,
                        login,
                        tokens.access,
                        units,
                        active,
                        period,
                        timezone,
                        throttle,
                        current=period == windows["current"],
                    )
                error = None
            except BudgetExhausted:
                store.record_load(login.country, kind, period, error_code="request_budget")
                store.record_load(
                    login.country,
                    "country_attempt",
                    windows["current"],
                    error_code="request_budget",
                )
                return outcomes
            except (client.DodoisError, ValueError, DbError) as exc:
                count, error = 0, _error(exc)
                logger.warning("Operating metrics %s/%s failed (%s)", login.country, kind, error)
            store.record_load(login.country, kind, period, error_code=error)
            outcomes.append(Outcome(login.country, kind, period, count, error))
    if fallback:
        logger.info("Operating metrics %s use explicit UTC fallback", login.country)
    store.record_load(login.country, "country_attempt", windows["current"])
    return outcomes


def run_pass(*, now: datetime | None = None, sleep: Sleep = time.sleep) -> list[Outcome]:
    """At most three least-recently attempted countries per existing hourly job."""
    moment = now or datetime.now(UTC)
    candidates = []
    budget = Budget()
    for login in logins.list_logins():
        if login.state == rules.EXPIRED:
            continue
        timezone, _ = country_timezone(login.country)
        cutoff = last_complete_day([timezone], now=moment)
        period = comparison_windows(cutoff)["current"]
        states = store.load_states([login.country], period)
        marker = next((row for row in states if row["kind"] == "country_attempt"), None)
        if marker and moment - datetime.fromisoformat(marker["attempted_at"]) < RETRY_AFTER:
            continue
        needs_work = False
        for window in planned_windows(cutoff):
            window_states = (
                states if window == period else store.load_states([login.country], window)
            )
            kinds = [*PATHS, "lfl_day", "lfl_month"] if window == period else list(PATHS)
            historical = window not in comparison_windows(cutoff).values()
            if any(_due(window_states, kind, moment, historical=historical) for kind in kinds):
                needs_work = True
                break
        if needs_work:
            candidates.append((marker["attempted_at"] if marker else "", login.country, login))
    outcomes: list[Outcome] = []
    for _, _, login in sorted(candidates)[:MAX_COUNTRIES_PER_PASS]:
        if budget.remaining <= 0:
            break
        try:
            outcomes.extend(collect_country(login, now=moment, sleep=sleep, budget=budget))
        except BudgetExhausted:
            break
        except (client.DodoisError, ValueError, DbError) as exc:
            logger.warning("Operating metrics %s unavailable (%s)", login.country, _error(exc))
    return outcomes
