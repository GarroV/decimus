"""Свежесть источников рейтингов — таблица под значком «?» у заголовка (D659).

Чистая классификация без обращений к базе: что прочитано, собирает вызывающий
(`src.web.ratings_freshness`), здесь — только цвет и порядок строк.

Правило владельца (27.10.2026): зелёный — обновлено сегодня, жёлтый — со вчера и в
течение трёх дней, красный — не обновлялось больше трёх дней. Для источников, которые
бот собирает раз в сутки (карты, площадки доставки), «сегодня» считается от периодичности
сбора, а не от смены календарной даты: данные, пришедшие вчера вечером, ночью ещё свежие
(13.11.2026, `classify_daily`). Рейтинг стандартов (РС)
выходит два раза в месяц, РКО — раз в неделю: для них свежесть считается не от
времени загрузки, а от конца периода, за который есть оценки, плюс обычная задержка
публикации, замеренная на данных.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from enum import StrEnum
from zoneinfo import ZoneInfo


class Status(StrEnum):
    """Порядок объявления — от лучшего к худшему: `worst` берёт максимум по нему."""

    FRESH = "fresh"
    LAG = "lag"
    STALE = "stale"


#: Таблица контроля (проверка раз в несколько часов): сегодня — зелёный, до трёх суток назад —
#: жёлтый, дальше — красный; считается по календарным суткам.
ROUTINE_GREEN_DAYS = 0
ROUTINE_YELLOW_DAYS = 3
#: Карты и площадки доставки бот собирает раз в сутки (сбор запускается, когда прошло 20 часов
#: с прошлого). Свежие — пока не прошли сутки с запасом на сдвиг запуска и на сам сбор; жёлтый —
#: один-три пропущенных запуска (сбой сборщика), красный — дальше.
DAILY_GREEN_HOURS = 36
DAILY_YELLOW_HOURS = 96
#: РС — полмесяца (1–15 и 16–конец): 15 дней следующего периода и ~7 дней задержки
#: публикации, замеренной на данных, — это ещё не опоздание.
RS_GREEN_DAYS = 22
RS_YELLOW_DAYS = 25
#: РКО — неделя пн–вс: 7 дней и ~4 дня задержки.
RKO_GREEN_DAYS = 11
RKO_YELLOW_DAYS = 14

KIND_RS = "rs"
KIND_RKO = "rko"
KIND_SHEET = "sheet"
KIND_MAPS = "maps"
KIND_AGG = "agg"

_PERIOD_LIMITS = {
    KIND_RS: (RS_GREEN_DAYS, RS_YELLOW_DAYS),
    KIND_RKO: (RKO_GREEN_DAYS, RKO_YELLOW_DAYS),
}
#: Площадки, которые владелец смотрит первыми; остальные — следом по коду.
_AGG_ORDER = ("wolt", "glovo", "bolt_food", "yandex_eda")


def _by_limits(days: int, green: int, yellow: int) -> Status:
    if days <= green:
        return Status.FRESH
    return Status.LAG if days <= yellow else Status.STALE


def classify_period(kind: str, end_on: date, today: date) -> Status:
    """Свежесть рейтинга по концу последнего периода с оценками (`rs` или `rko`)."""
    green, yellow = _PERIOD_LIMITS[kind]
    return _by_limits((today - end_on).days, green, yellow)


def local_zone() -> tzinfo:
    """Часовой пояс сутки и время прихода: `TZ` окружения сервера, как на остальных экранах.

    Не задан — UTC: так тесты не зависят от машины, на которой идут.
    """
    name = os.environ.get("TZ")
    return ZoneInfo(name) if name else UTC


def classify_age(at: datetime, today: date) -> Status:
    """Свежесть по календарным суткам события: сегодня, 1–3 дня, больше.

    Сутки — в часовом поясе сервера, как время на остальных экранах.
    """
    days = (today - at.astimezone(local_zone()).date()).days
    return _by_limits(days, ROUTINE_GREEN_DAYS, ROUTINE_YELLOW_DAYS)


def classify_daily(at: datetime, now: datetime) -> Status:
    """Свежесть источника, который собирается раз в сутки: по возрасту в часах, а не по дате.

    Данные от вчера 17:25, увиденные в 01:00, — 8 часов, это свежо; жёлтым источник
    становится, только когда сбор действительно пропустил прогон.
    """
    hours = (now - at).total_seconds() / 3600
    if hours <= DAILY_GREEN_HOURS:
        return Status.FRESH
    return Status.LAG if hours <= DAILY_YELLOW_HOURS else Status.STALE


def worst(statuses: Iterable[Status]) -> Status | None:
    """Худший из статусов (`None` — строк нет)."""
    order = list(Status)
    return max(statuses, key=order.index, default=None)


@dataclass(frozen=True)
class PeriodFact:
    """Последний период рейтинга с оценками и когда они пришли."""

    begin_on: date
    end_on: date
    arrived: datetime | None


@dataclass(frozen=True)
class Row:
    """Строка таблицы: `kind` — вид источника, `code` — площадка у агрегаторов."""

    kind: str
    status: Status
    code: str = ""
    begin_on: date | None = None
    end_on: date | None = None
    arrived: datetime | None = None
    #: Сколько площадок свёрнуто в строку (`collapse_aggregators`); у остальных 0.
    count: int = 0


def _period_row(kind: str, fact: PeriodFact | None, today: date) -> Row:
    if fact is None:
        return Row(kind, Status.STALE)
    return Row(
        kind,
        classify_period(kind, fact.end_on, today),
        begin_on=fact.begin_on,
        end_on=fact.end_on,
        arrived=fact.arrived,
    )


def _age_row(kind: str, at: datetime | None, today: date, code: str = "") -> Row:
    if at is None:
        return Row(kind, Status.STALE, code)
    return Row(kind, classify_age(at, today), code, arrived=at)


def _daily_row(kind: str, at: datetime | None, now: datetime, code: str = "") -> Row:
    if at is None:
        return Row(kind, Status.STALE, code)
    return Row(kind, classify_daily(at, now), code, arrived=at)


def collapse_aggregators(rows: Iterable[Row]) -> tuple[Row, ...]:
    """Строки всех площадок — в одну: худший цвет и самое раннее время прихода."""
    rows = tuple(rows)
    aggs = [r for r in rows if r.kind == KIND_AGG]
    if not aggs:
        return rows
    arrived = [r.arrived for r in aggs]
    one = Row(
        KIND_AGG,
        worst(r.status for r in aggs) or Status.STALE,
        arrived=None if None in arrived else min(a for a in arrived if a),
        count=len(aggs),
    )
    first = next(i for i, r in enumerate(rows) if r.kind == KIND_AGG)
    rest = tuple(r for r in rows if r.kind != KIND_AGG)
    return (*rest[:first], one, *rest[first:])


def _agg_rank(code: str) -> tuple[int, str]:
    return (_AGG_ORDER.index(code) if code in _AGG_ORDER else len(_AGG_ORDER), code)


def build(
    *,
    today: date,
    now: datetime,
    rs: PeriodFact | None,
    rko: PeriodFact | None,
    sheet_checked: datetime | None,
    maps_loaded: datetime | None,
    aggregators: Mapping[str, datetime],
) -> tuple[Row, ...]:
    """Строки в неизменном порядке: РС, РКО, таблица контроля, карты, площадки.

    Таблицу контроля бот ни разу не проверял — она не подключена (демо, стенд):
    строки нет, а не красная «ни разу».
    """
    return (
        _period_row(KIND_RS, rs, today),
        _period_row(KIND_RKO, rko, today),
        *((_age_row(KIND_SHEET, sheet_checked, today),) if sheet_checked else ()),
        _daily_row(KIND_MAPS, maps_loaded, now),
        *(_daily_row(KIND_AGG, aggregators[c], now, c) for c in sorted(aggregators, key=_agg_rank)),
    )
