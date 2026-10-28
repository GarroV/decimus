"""Суточный сбор данных Dodo IS для «Качества» по странам (D671): продажи, агрегаторы, КР.

Здесь порядок, а не сеть и не SQL: сеть — `client.api_get`, разбор и свёртка —
`src/domain/dodois_metrics.py`, база — `src/db/dodois_metrics_store.py`.

**Ключи не продлеваются здесь.** Вход страны продлевает только `service.run_pass` (ключ
продления одноразовый, D640); этот модуль лишь читает действующий ключ доступа из базы и ходит
с ним в `api` — одними GET. Страна с истёкшим входом пропускается молча: причину уже показывает
вкладка «Подключения».

**Что и откуда** (все права входа уже выданы: `shared sales ...`):
- `finances/sales/units` — продажи по источнику заказа и каналу; окна по `SALES_WINDOW_DAYS`
  суток, строки одной пиццерии складываются в месяц;
- `accounting/sales` с `orderSource=Aggregator` — построчные заказы; в базу идёт только свёртка
  «пиццерия × агрегатор × месяц», строки заказов не хранятся и не логируются;
- `customer-feedback/customer-ratings` — среднее и число оценок, месяц одним окном.
- `controlling/ratings/customer-experience/history`, `controlling/ratings/standards/history` и
  `controlling/checkups` — оценки РКО и РС по неделям и счёт проверок (вид вызова `ratings`); путь
  без префикса страны, окна по месяцу, до 100 пиццерий и постраничная выдача.

**Месяц заменяется целиком** для пиццерий, ответивших в заход. Первая удачная загрузка вида
берёт 12 полных месяцев и текущий, дальше — прошлый и текущий. Пиццерия, к которой у входа нет
доступа (403 `NoAccessToUnit`), выделяется делением пачки пополам и пропускается.

Журнал — строка на страну и вид (`dodois.metric_loads`). Новых оповещений людям нет.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.db import dodois_logins as logins
from src.db import dodois_metrics_store as store
from src.db.errors import DbError
from src.domain import dodois as rules
from src.domain import dodois_metrics as parse
from src.domain.dodois import Login

from . import client
from .client import DodoisError, Response

logger = logging.getLogger(__name__)

SALES_PATH = "/dodopizza/{cc}/finances/sales/units"
ACCOUNTING_PATH = "/dodopizza/{cc}/accounting/sales"
#: Оценки клиентов не привязаны к стране в пути: пиццерии названы в запросе.
KR_PATH = "/customer-feedback/customer-ratings"

#: Пиццерий в одном запросе: продажи и заказы — до 30, оценки — до 100 (документация).
SALES_UNITS_PER_CALL = 30
KR_UNITS_PER_CALL = 100
#: Строк на страницу заказов и предохранитель от бесконечной выдачи.
PAGE_SIZE = 1000
MAX_PAGES = 500
#: Пауза между запросами, чтобы не упереться в лимит Dodo IS.
PAUSE_SEC = 0.25
#: Сколько вид данных считается свежим: суточный сбор, с запасом на сдвиг часов.
FRESH_FOR = timedelta(hours=20)
ORDER_SOURCE_AGGREGATOR = "Aggregator"

Sleep = Callable[[float], None]


@dataclass(frozen=True)
class Outcome:
    country: str
    kind: str
    ok: bool
    rows: int
    error: str | None = None


def _stamp(day: date, *, end: bool) -> str:
    return f"{day.isoformat()}T{'23:59:59' if end else '00:00:00'}"


def _batches(units: list[str], size: int) -> list[list[str]]:
    return [units[i : i + size] for i in range(0, len(units), size)]


def _each_batch(
    units: list[str], size: int, get: Callable[[list[str]], Response]
) -> Iterator[tuple[list[str], Any]]:
    """Пачки пиццерий с ответом 200; отказ по доступу делит пачку, пока не найдёт, на ком он."""
    queue = _batches(units, size)
    while queue:
        batch = queue.pop(0)
        response = get(batch)
        if response.status == 200:
            yield batch, response.body
        elif len(batch) > 1:
            middle = len(batch) // 2
            queue[:0] = [batch[:middle], batch[middle:]]


def _sales_month(
    country: str, contour: str, token: str, units: list[str], month: date, today: date, sleep: Sleep
) -> tuple[list[str], list[parse.SalesRow]]:
    end = parse.month_end(month, today)
    rows: list[parse.SalesRow] = []
    covered: list[str] = []
    for start, stop in parse.windows(month, end, parse.SALES_WINDOW_DAYS):

        def get(batch: list[str], start: date = start, stop: date = stop) -> Response:
            sleep(PAUSE_SEC)
            query = {
                "from": _stamp(start, end=False),
                "to": _stamp(stop, end=True),
                "units": ",".join(batch),
            }
            return client.api_get(contour, SALES_PATH.format(cc=country.lower()), query, token)

        window_covered: list[str] = []
        for batch, body in _each_batch(units, SALES_UNITS_PER_CALL, get):
            rows.extend(parse.sales_rows(body))
            window_covered.extend(batch)
        covered = window_covered
    return covered, parse.merge_sales(rows)


def _paged(
    contour: str,
    path: str,
    base: dict[str, str],
    token: str,
    sleep: Sleep,
    page_size: int = PAGE_SIZE,
) -> Response:
    """Все страницы выдачи одним ответом: 200 с общим списком строк; отказ по доступу — как есть."""
    collected: list[Any] = []
    for page in range(MAX_PAGES):
        sleep(PAUSE_SEC)
        query = {**base, "skip": str(page * page_size), "take": str(page_size)}
        response = client.api_get(contour, path, query, token)
        if response.status != 200:
            return response
        items = parse.items_of(response.body)
        collected.extend(items)
        if not items or parse.is_end_of_list(response.body, len(items), page_size):
            return Response(200, {}, collected)
    raise parse.ShapeError("выдача не кончается: предел страниц")


def _aggregators_month(
    country: str, contour: str, token: str, units: list[str], month: date, today: date, sleep: Sleep
) -> tuple[list[str], list[parse.AggregatorMonth]]:
    end = parse.month_end(month, today)
    orders: list[parse.AggregatorOrder] = []
    covered: list[str] = []
    if end < month:
        return [], []

    def get(batch: list[str]) -> Response:
        base = {
            "from": _stamp(month, end=False),
            "to": _stamp(end, end=True),
            "units": ",".join(batch),
            "orderSource": ORDER_SOURCE_AGGREGATOR,
        }
        return _paged(contour, ACCOUNTING_PATH.format(cc=country.lower()), base, token, sleep)

    for batch, body in _each_batch(units, SALES_UNITS_PER_CALL, get):
        orders.extend(parse.aggregator_orders(body))
        covered.extend(batch)
    return covered, parse.sum_aggregators(orders)


def _kr_month(
    country: str, contour: str, token: str, units: list[str], month: date, today: date, sleep: Sleep
) -> tuple[list[str], list[parse.KrRow]]:
    end = parse.month_end(month, today)
    rows: list[parse.KrRow] = []
    covered: list[str] = []
    if end < month:
        return [], []

    def get(batch: list[str]) -> Response:
        sleep(PAUSE_SEC)
        query = {"units": ",".join(batch), "from": month.isoformat(), "to": end.isoformat()}
        return client.api_get(contour, KR_PATH, query, token)

    for batch, body in _each_batch(units, KR_UNITS_PER_CALL, get):
        rows.extend(parse.kr_rows(body))
        covered.extend(batch)
    return covered, rows


def _ratings_range(
    contour: str, token: str, units: list[str], months: list[date], today: date, sleep: Sleep
) -> int:
    """Оценки РКО и РС по периодам и счёт проверок за месяцы; вернуть число легших строк.

    Окна — по месяцу (предел диапазона в документации не назван); период, попавший в два окна,
    берётся один раз. Заменяются периоды, начавшиеся от первого дня старшего месяца до сегодня.
    """
    start, stop = min(months), today
    covered: set[str] | None = None
    ratings: list[parse.RatingPeriod] = []
    checkups: list[Any] = []
    for month in sorted(months):
        end = min(parse.next_month(month) - timedelta(days=1), today)
        window = {"fromDate": month.isoformat(), "toDate": end.isoformat()}
        calls = [(path, kind) for kind, path in parse.RATING_PATHS.items()]
        calls.append((parse.CHECKUPS_PATH, ""))
        for path, kind in calls:

            def get(
                batch: list[str], path: str = path, window: dict[str, str] = window
            ) -> Response:
                return _paged(
                    contour, path, {**window, "units": ",".join(batch)}, token, sleep, PAGE_SIZE
                )

            answered: set[str] = set()
            for batch, items in _each_batch(units, KR_UNITS_PER_CALL, get):
                answered.update(batch)
                if kind:
                    ratings.extend(parse.rating_periods(items, kind))
                else:
                    checkups.extend(items)
            covered = answered if covered is None else covered & answered
    done = sorted(covered or ())
    total = store.replace_rating_periods(start, stop, done, parse.merge_rating_periods(ratings))
    return total + store.replace_checkup_periods(start, stop, done, parse.checkup_periods(checkups))


def _collect_kind(
    kind: str,
    country: str,
    login: Login,
    token: str,
    units: list[str],
    months: list[date],
    today: date,
    sleep: Sleep,
) -> int:
    """Загрузить вид данных за месяцы, свежие первыми; вернуть число легших строк."""
    if kind == parse.KIND_RATINGS:
        return _ratings_range(login.contour, token, units, months, today, sleep)
    total = 0
    for month in months:
        if kind == parse.KIND_SALES:
            covered, sales = _sales_month(country, login.contour, token, units, month, today, sleep)
            total += store.replace_sales(month, covered, sales)
        elif kind == parse.KIND_AGGREGATORS:
            covered, agg = _aggregators_month(
                country, login.contour, token, units, month, today, sleep
            )
            total += store.replace_aggregators(month, covered, agg)
        else:
            covered, kr = _kr_month(country, login.contour, token, units, month, today, sleep)
            total += store.replace_kr(month, covered, kr)
    return total


def _error_text(exc: Exception) -> str:
    """Причина отказа для журнала: вид отказа Dodo IS, имена ключей ответа или класс ошибки базы."""
    if isinstance(exc, DodoisError):
        return exc.kind
    if isinstance(exc, parse.ShapeError):
        return f"unknown_shape: {exc}"
    return f"db_failed: {exc.__class__.__name__}"


def collect_country(
    login: Login, kinds: list[str], *, today: date, sleep: Sleep = time.sleep
) -> list[Outcome]:
    """Собрать для страны перечисленные виды данных; исход каждого — в журнал и в ответ."""
    country = login.country
    try:
        tokens = logins.read_tokens(country)
    except DbError:
        tokens = None
    if tokens is None:
        return [Outcome(country, kind, False, 0, "no_tokens") for kind in kinds]
    try:
        units = sorted(set(client.working_pizzerias(country)) | set(store.country_units(country)))
    except (DodoisError, DbError) as exc:
        return [Outcome(country, kind, False, 0, _error_text(exc)) for kind in kinds]
    units = [u for u in units if parse.unit_id(u)]
    outcomes: list[Outcome] = []
    for kind in kinds:
        load_id = store.start_load(country, kind)
        try:
            backfill = not store.has_ok_load(country, kind)
            months = parse.months_to_load(today, backfill=backfill)
            rows = _collect_kind(kind, country, login, tokens.access, units, months, today, sleep)
            outcome = Outcome(country, kind, True, rows)
        except (DodoisError, parse.ShapeError, DbError) as exc:
            logger.warning("Dodo IS %s/%s: сбор не удался (%s)", country, kind, _error_text(exc))
            outcome = Outcome(country, kind, False, 0, _error_text(exc))
        try:
            store.finish_load(load_id, ok=outcome.ok, rows=outcome.rows, error=outcome.error)
        except DbError:
            logger.error("Dodo IS %s/%s: итог сбора не записался", country, kind)
        outcomes.append(outcome)
    return outcomes


def due_kinds(country: str, now: datetime) -> list[str]:
    """Виды данных страны, которым пора: ни разу не удавались или последняя удача старше суток."""
    due: list[str] = []
    for kind in parse.KINDS:
        last = store.last_ok_at(country, kind)
        if last is None or now - last >= FRESH_FOR:
            due.append(kind)
    return due


def run_pass(*, now: datetime | None = None, sleep: Sleep = time.sleep) -> list[Outcome]:
    """Один заход бота: у каждой страны с действующим входом собрать то, что пора."""
    moment = now or datetime.now(UTC)
    outcomes: list[Outcome] = []
    for login in logins.list_logins():
        if login.state == rules.EXPIRED:
            continue
        try:
            kinds = due_kinds(login.country, moment)
            if kinds:
                outcomes.extend(collect_country(login, kinds, today=moment.date(), sleep=sleep))
        except Exception:
            logger.exception("Dodo IS %s: сбор данных для «Качества» упал", login.country)
    return outcomes
