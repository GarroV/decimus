"""Данные Dodo IS для страницы «Качество» (D671): разбор ответов и свёртка в «пиццерия × месяц».

Чистые функции без сети и базы. Сеть и порядок — `src/dodois/metrics.py`, база —
`src/db/dodois_metrics_store.py` (запись) и `src/db/dodois_metrics.py` (чтение).

**Форма ответов.** Продажи по источнику и каналу (`finances/sales/units`) и заказы
(`accounting/sales`) в открытой документации не расписаны полем за полем, поэтому разбор
терпимый: список ищется под несколькими именами, строка продаж — рекурсивно, имена полей
счёта и выручки — из короткого списка вариантов. Что не разобралось — не угадывается молча:
`ShapeError` несёт имена ключей первой непонятой строки (значений нет), и загрузка
записывается как неудачная. Оценки клиентов (`customer-ratings`) расписаны в документации
точно: `{"customerRatings": [{unitId, avgDineInOrderRate, ...}]}`.

**Данных людей здесь нет:** из ответа берутся код пиццерии, источник, канал, агрегатор,
число и сумма. Остальные поля строки отбрасываются сразу.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

#: Виды загрузки — как в `dodois.metric_loads.kind`.
KIND_SALES = "sales"
KIND_AGGREGATORS = "aggregators"
KIND_KR = "kr"
KIND_RATINGS = "ratings"
KINDS = (KIND_SALES, KIND_AGGREGATORS, KIND_KR, KIND_RATINGS)

#: Сколько полных месяцев берём при первой загрузке страны, помимо текущего.
BACKFILL_MONTHS = 12
#: Окно запроса продаж по пиццериям — дней (в документации «не больше 31»; берём меньше).
SALES_WINDOW_DAYS = 7

#: Агрегатор без имени у Dodo IS называется так; в «заказы агрегаторов» такое не входит.
UNDEFINED_AGGREGATOR = "undefined"

_UNIT = re.compile(r"[0-9a-f]{32}")
_LIST_KEYS = (
    "result",
    "sales",
    "units",
    "unitsSales",
    "items",
    "data",
    "customerRatings",
    "unitRates",
    "checkups",
)
_ORDERS_KEYS = ("ordersCount", "orderCount", "ordersQuantity", "count", "orders", "salesCount")
_REVENUE_KEYS = (
    "sales",
    "revenue",
    "salesAmount",
    "totalAmount",
    "amount",
    "totalSales",
    "price",
    "totalPrice",
    "sum",
)
_CURRENCY_KEYS = ("currency", "currencyCode")
#: Глубина поиска строк продаж внутри ответа: дальше искать нечего, это защита от вложенности.
_MAX_DEPTH = 4


class ShapeError(ValueError):
    """Ответ не той формы, которую умеем читать. Текст — только имена ключей, без значений."""


@dataclass(frozen=True)
class SalesRow:
    dodo_id: str
    order_source: str
    sales_channel: str
    orders: int
    revenue: Decimal
    currency: str | None


@dataclass(frozen=True)
class AggregatorOrder:
    """Одна строка продажи агрегатора, уже без лишних полей: счёт берёт у неё одну единицу."""

    dodo_id: str
    aggregator: str


@dataclass(frozen=True)
class AggregatorMonth:
    dodo_id: str
    aggregator: str
    orders: int
    #: Выручки по агрегатору нет: у заказа `accounting/sales` денежного поля верхнего уровня
    #: нет (сумма внутри `products`), форма `products` в документации не расписана — не гадаем.
    revenue: Decimal | None = None


@dataclass(frozen=True)
class RatingPeriod:
    dodo_id: str
    kind: str
    period_from: date
    period_to: date
    rate: Decimal
    publish_status: str | None


@dataclass(frozen=True)
class CheckupPeriod:
    dodo_id: str
    kind: str
    period_from: date
    period_to: date
    checkups: int
    by_status: dict[str, int]


@dataclass(frozen=True)
class KrRow:
    dodo_id: str
    dine_in_avg: Decimal | None
    dine_in_count: int
    delivery_avg: Decimal | None
    delivery_count: int


def unit_id(value: Any) -> str | None:
    """Код пиццерии в виде 32 строчных шестнадцатеричных знаков; иное — `None`."""
    if not isinstance(value, str):
        return None
    flat = value.replace("-", "").lower()
    return flat if _UNIT.fullmatch(flat) else None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        found = Decimal(str(value))
    except InvalidOperation:
        return None
    return found if found.is_finite() else None


def _first_number(node: Mapping[str, Any], keys: Sequence[str]) -> Decimal | None:
    for key in keys:
        if key in node:
            found = _number(node[key])
            if found is not None:
                return found
    return None


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _currency(node: Mapping[str, Any]) -> str | None:
    for key in _CURRENCY_KEYS:
        found = _text(node.get(key))
        if found:
            return found[:8]
    return None


def _shape_note(node: Any) -> str:
    keys = sorted(node)[:12] if isinstance(node, dict) else [type(node).__name__]
    return ",".join(str(k)[:30] for k in keys)


def items_of(body: Any) -> list[Any]:
    """Список строк ответа: сам список, либо значение под одним из привычных имён."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in _LIST_KEYS:
            if isinstance(body.get(key), list):
                return list(body[key])
        lists = [v for v in body.values() if isinstance(v, list)]
        if len(lists) == 1:
            return list(lists[0])
        if not lists:
            return []
    raise ShapeError(f"список строк не найден; ключи: {_shape_note(body)}")


def is_end_of_list(body: Any, taken: int, page_size: int) -> bool:
    """Конец постраничной выдачи: `isEndOfListReached`, а без него — неполная страница."""
    if isinstance(body, dict) and isinstance(body.get("isEndOfListReached"), bool):
        return bool(body["isEndOfListReached"])
    return taken < page_size


def _leaves(
    node: Any, unit: str | None, depth: int = 0
) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """Строки продаж по источнику и каналу: словари с `orderSource`, где бы они ни лежали."""
    if depth > _MAX_DEPTH:
        return
    if isinstance(node, list):
        for child in node:
            yield from _leaves(child, unit, depth + 1)
    elif isinstance(node, dict):
        own = unit_id(node.get("unitId")) or unit
        if "orderSource" in node or "salesChannel" in node:
            yield own, node
            return
        for child in node.values():
            if isinstance(child, list | dict):
                yield from _leaves(child, own, depth + 1)


def sales_rows(body: Any) -> list[SalesRow]:
    """Разобрать ответ `finances/sales/units`; пустой — пустой список, непонятный — `ShapeError`."""
    items = items_of(body)
    rows: list[SalesRow] = []
    unread: Any = None
    for item in items:
        for unit, leaf in _leaves(item, None):
            source, channel = _text(leaf.get("orderSource")), _text(leaf.get("salesChannel"))
            orders = _first_number(leaf, _ORDERS_KEYS)
            revenue = _first_number(leaf, _REVENUE_KEYS)
            if unit and source and channel and orders is not None and revenue is not None:
                rows.append(SalesRow(unit, source, channel, int(orders), revenue, _currency(leaf)))
            elif unread is None:
                unread = leaf
    if items and not rows:
        raise ShapeError(f"продажи не разобрались; ключи строки: {_shape_note(unread or items[0])}")
    return rows


def merge_sales(rows: Iterable[SalesRow]) -> list[SalesRow]:
    """Сложить строки одной пиццерии, источника и канала (окна запроса дают их несколько)."""
    totals: dict[tuple[str, str, str], tuple[int, Decimal, str | None]] = {}
    for row in rows:
        key = (row.dodo_id, row.order_source, row.sales_channel)
        orders, revenue, currency = totals.get(key, (0, Decimal(0), None))
        totals[key] = (orders + row.orders, revenue + row.revenue, currency or row.currency)
    return [SalesRow(*key, *value) for key, value in sorted(totals.items())]


def aggregator_orders(body: Any) -> list[AggregatorOrder]:
    """Разобрать страницу `accounting/sales`: строки с непустым агрегатором, остальные — мимо.

    Ключи заказа: `unitId`, `aggregatorName`, `orderSource`, `salesChannel`, `paymentMethod`,
    `soldAt`, `products`. Денежного поля верхнего уровня нет, поэтому берётся только счёт.
    """
    items = items_of(body)
    found: list[AggregatorOrder] = []
    shaped = False
    unread: Any = None
    for item in items:
        unit = unit_id(item.get("unitId")) if isinstance(item, dict) else None
        if unit is None:
            unread = unread if unread is not None else item
            continue
        shaped = True
        name = _text(item.get("aggregatorName"))
        if name and name.lower() != UNDEFINED_AGGREGATOR:
            found.append(AggregatorOrder(unit, name[:60]))
    if items and not shaped:
        raise ShapeError(f"заказы не разобрались; ключи строки: {_shape_note(unread)}")
    return found


def sum_aggregators(orders: Iterable[AggregatorOrder]) -> list[AggregatorMonth]:
    """Свернуть строки заказов в «пиццерия × агрегатор»: сколько заказов."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for order in orders:
        counts[(order.dodo_id, order.aggregator)] += 1
    return [AggregatorMonth(*key, counts[key]) for key in sorted(counts)]


def kr_rows(body: Any) -> list[KrRow]:
    """Разобрать ответ `customer-ratings`: `{"customerRatings": [...]}`."""
    if not isinstance(body, dict) or not isinstance(body.get("customerRatings"), list):
        raise ShapeError(f"нет списка customerRatings; ключи: {_shape_note(body)}")
    rows: list[KrRow] = []
    for item in body["customerRatings"]:
        unit = unit_id(item.get("unitId")) if isinstance(item, dict) else None
        if unit is None:
            raise ShapeError(f"строка оценок без кода пиццерии; ключи: {_shape_note(item)}")
        dine_n = int(_first_number(item, ("dineInRateCount",)) or 0)
        deli_n = int(_first_number(item, ("deliveryRateCount",)) or 0)
        rows.append(
            KrRow(
                unit,
                _first_number(item, ("avgDineInOrderRate",)) if dine_n else None,
                dine_n,
                _first_number(item, ("avgDeliveryOrderRate",)) if deli_n else None,
                deli_n,
            )
        )
    return rows


# --- месяцы и окна --------------------------------------------------------------------


def first_of_month(day: date) -> date:
    return day.replace(day=1)


def next_month(month: date) -> date:
    return (month.replace(day=28) + timedelta(days=4)).replace(day=1)


def previous_month(month: date) -> date:
    return first_of_month(month - timedelta(days=1))


def months_to_load(today: date, *, backfill: bool) -> list[date]:
    """Какие месяцы заменить за заход: текущий и прошлый, а при первой загрузке — 12 полных."""
    months = [first_of_month(today)]
    for _ in range(BACKFILL_MONTHS if backfill else 1):
        months.append(previous_month(months[-1]))
    return months


def month_end(month: date, today: date) -> date:
    """Последний день месяца, но не позже вчерашнего: за сегодня Dodo IS данных не отдаёт."""
    return min(next_month(month) - timedelta(days=1), today - timedelta(days=1))


def windows(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Разбить [start, end] на отрезки не длиннее `days` суток; пусто, если end < start."""
    found: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=days - 1), end)
        found.append((cursor, stop))
        cursor = stop + timedelta(days=1)
    return found


# --- оценки контроля (РКО, РС) и проверки ----------------------------------------------

RATING_RKO = "rko"
RATING_RS = "rs"
#: Пути `controlling/*` — без префикса страны; вид оценки — по пути, а не по ответу.
RATING_PATHS = {
    RATING_RKO: "/controlling/ratings/customer-experience/history",
    RATING_RS: "/controlling/ratings/standards/history",
}
CHECKUPS_PATH = "/controlling/checkups"


def _day(value: Any) -> date | None:
    """Дата из `YYYY-MM-DD` или из строки времени, начинающейся с даты."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def rating_kind(raw: Any) -> str:
    """Вид оценки из `ratingKind` проверки: РС и РКО, иное — как есть, в нижнем регистре."""
    text = (_text(raw) or "unknown").lower()
    if "standard" in text or text == RATING_RS:
        return RATING_RS
    if "customer" in text or "experience" in text or text == RATING_RKO:
        return RATING_RKO
    return text[:40]


def rating_periods(body: Any, kind: str) -> list[RatingPeriod]:
    """Разобрать `{"unitRates": [...]}` оценок РКО или РС по периодам."""
    items = items_of(body)
    rows: list[RatingPeriod] = []
    for item in items:
        if not isinstance(item, dict):
            raise ShapeError(f"строка оценок периода не словарь: {_shape_note(item)}")
        unit = unit_id(item.get("unitId"))
        start, stop = _day(item.get("periodFrom")), _day(item.get("periodTo"))
        rate = _first_number(item, ("rate",))
        if unit is None or start is None or stop is None or rate is None:
            raise ShapeError(f"оценка периода не разобралась; ключи: {_shape_note(item)}")
        rows.append(RatingPeriod(unit, kind, start, stop, rate, _text(item.get("publishStatus"))))
    return rows


def checkup_periods(body: Any) -> list[CheckupPeriod]:
    """Свернуть проверки (ответ или строки из нескольких окон) в счёт по периодам."""
    counts: dict[tuple[str, str, date, date], dict[str, int]] = {}
    seen: set[str] = set()
    for item in items_of(body):
        if not isinstance(item, dict):
            raise ShapeError(f"строка проверки не словарь: {_shape_note(item)}")
        # Номер нужен только чтобы не посчитать дважды проверку, пришедшую из двух окон запроса;
        # дальше он не идёт.
        number = _text(item.get("id"))
        if number is not None:
            if number in seen:
                continue
            seen.add(number)
        unit = unit_id(item.get("unitId"))
        start, stop = _day(item.get("periodFrom")), _day(item.get("periodTo"))
        if unit is None or start is None or stop is None:
            raise ShapeError(f"проверка не разобралась; ключи: {_shape_note(item)}")
        status = (_text(item.get("status")) or "unknown")[:40]
        key = (unit, rating_kind(item.get("ratingKind")), start, stop)
        by_status = counts.setdefault(key, {})
        by_status[status] = by_status.get(status, 0) + 1
    return [
        CheckupPeriod(*key, sum(by_status.values()), by_status)
        for key, by_status in sorted(counts.items())
    ]


def merge_rating_periods(rows: Iterable[RatingPeriod]) -> list[RatingPeriod]:
    """Одна строка на пиццерию, вид и начало периода: окна запроса могут вернуть период дважды."""
    unique = {(r.dodo_id, r.kind, r.period_from): r for r in rows}
    return [unique[k] for k in sorted(unique)]
