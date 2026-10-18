"""Чтение рейтингов через Claude (D420): сводка, пиццерии, состояние агрегаторов.

Три правила.

**Числа — те же функции, что у экрана «Рейтинги».** Средние группы — `report`
(`select`, `build_groups`, `summary.group_average` по D353), агрегаторы —
`agg_store`, карты — `maps_store`: здесь отбор, охват и форма ответа, а не
подсчёт. Расхождение между экраном и ответом инструмента было бы двумя
«официальными» цифрами.

**Охват — по токену.** Рейтинги видят все (D327), но инструмент отдаёт партнёру
страны его пространства (`reach_of`, как инструменты проверок), а УК — всё. Страна
вне охвата отвечает тем же отказом, что неизвестная: чужой список стран по
отказам не выведывается. Аргумента `tenant` у инструментов нет — его назвал бы
кто угодно.

**Незнакомое значение — отказ, а не молчаливая замена.** Экран подставляет первый
допустимый срез или период по умолчанию; агент, получив другой период под видом
запрошенного, процитирует его как запрошенный. Здесь неверное значение отвечает
отказом со списком допустимых, а выбранный период приходит в ответе.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from ..db import agg_store
from ..db import ratings_read as read
from ..db.errors import ConfigError as DbConfigError
from ..db.errors import RatingsError
from ..db.reach import reach_of
from ..domain.tenants import HQ_TENANT, canonical_tenant
from ..ratings import report, units_view
from ..ratings.aggregators import queue
from ..ratings.periods import ReportPeriod, parse_period
from ..ratings.summary import shown
from .db_target import config_refusal
from .errors import ToolError

NOT_CONNECTED = (
    "Рейтинги на этом стенде не подключены: не задана переменная окружения DATABASE_URL. "
    "Это отказ чтения, а не отсутствие рейтингов"
)
READ_FAILED = "Рейтинги не прочитались: база отказала. Это отказ чтения, а не отсутствие данных"
NO_COUNTRIES = (
    "У этого пространства нет стран в охвате, поэтому рейтинги ему не показываются. "
    "Страны назначает управляющая компания"
)
NO_DATA = "За выбранный период оценок нет: рейтинги за него ещё не загружены"

SCORE_NOTE = "РС и РКО — баллы по шкале 0–100, средние округлены до 0,1, как на экране «Рейтинги»"
AGG_NOTE = (
    "Оценки агрегаторов — в родной шкале каждого: Wolt из 10, Glovo — % довольных (из 100), "
    "остальные из 5; в одну шкалу не сводятся. Карта — Google, из 5"
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
_GROUP_VALUES = ("imf", "cluster", "developer", "country")
_HEX32_LEN = 32


@contextmanager
def _ratings() -> Iterator[None]:
    """Отказ окружения базы и самой базы — отказом инструмента, а не сбоем разбора."""
    try:
        yield
    except DbConfigError as exc:
        raise config_refusal(exc, NOT_CONNECTED) from None
    except RatingsError as exc:
        raise ToolError(READ_FAILED) from exc


def _scope(tenant: str) -> tuple[str, ...] | None:
    """Страны, которые видит пространство: `None` — все (УК), иначе страны партнёра."""
    return reach_of(tenant).countries


def _iso(day: str | None, name: str) -> str | None:
    if day is None:
        return None
    try:
        date.fromisoformat(day.strip())
    except ValueError:
        raise ToolError(f"{name}: дата в формате ГГГГ-ММ-ДД, получено «{day}»") from None
    return day.strip()


def _period_args(period: str | None, date_from: str | None, date_to: str | None) -> dict[str, str]:
    """Период так же, как его понимает адрес экрана (`period` или `from` и `to`)."""
    begin, end = _iso(date_from, "date_from"), _iso(date_to, "date_to")
    if period and (begin or end):
        raise ToolError("Период задаётся либо period, либо парой date_from и date_to, не обоими")
    if (begin is None) != (end is None):
        raise ToolError("date_from и date_to задаются вместе")
    if begin and end:
        return {"from": begin, "to": end}
    return {"period": period.strip()} if period and period.strip() else {}


def _period_json(period: ReportPeriod | None) -> dict[str, str] | None:
    if period is None:
        return None
    return {
        "kind": period.kind,
        "key": period.key,
        "begin": period.begin.isoformat(),
        "end": period.end.isoformat(),
    }


def _selected(
    args: dict[str, str], only: tuple[str, ...] | None, *, group: str, value: str | None
) -> tuple[report.Selection, report.Choices]:
    """Отбор экрана с проверкой: период, срез и значение — без молчаливых замен."""
    if group not in report.GROUPS:
        raise ToolError(f"group_by: одно из {', '.join(report.GROUPS)}, получено «{group}»")
    asked = {**args, "group": group, **({"value": value} if value else {})}
    selection, found = report.select(asked, today=date.today(), only=only)
    if "period" in args and parse_period(args["period"], rs_periods=found.rs_periods) is None:
        raise ToolError(
            f"period: не узнан «{args['period']}». Форматы: месяц 2026-09, квартал 2026-Q3, "
            "период РС rs:<номер>, отрезок 2026-09-01..2026-09-30"
        )
    allowed: dict[str, tuple[str, ...]] = {
        report.GROUP_DEVELOPER: found.developers,
        report.GROUP_COUNTRY: tuple(row.code for row in found.countries),
        report.GROUP_CLUSTER: report.CLUSTERS,
    }
    if group in allowed and (value or "") not in allowed[group]:
        raise ToolError(
            f"value для group_by={group}: {'не задано' if not value else f'«{value}» недоступно'}. "
            f"Доступно: {', '.join(allowed[group]) or 'ничего'}"
        )
    return selection, found


def _group_name(line: report.GroupLine, selection: report.Selection, found: report.Choices) -> str:
    names = {row.code: row.name_ru for row in found.countries}
    clusters = {"CEE": "CEE", "TR": "Турция", "CAUCASUS": "Кавказ", "OTHER": "Остальные страны"}
    if line.level == report.LEVEL_COUNTRY and line.key:
        return names.get(line.key, line.key)
    if line.key is not None:
        return clusters.get(line.key, line.key)
    if selection.group == report.GROUP_COUNTRY and selection.value:
        return names.get(selection.value, selection.value)
    if selection.group == report.GROUP_CLUSTER and selection.value:
        return clusters.get(selection.value, selection.value)
    return selection.value or "Весь IMF"


def _shown(score: float | None) -> float | None:
    return None if score is None else shown(score)


def ratings_summary(
    *,
    tenant: str,
    group_by: str = "imf",
    value: str | None = None,
    period: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, object]:
    args = _period_args(period, date_from, date_to)
    with _ratings():
        only = _scope(tenant)
        if only == ():
            return {"status": "no_countries", "message": NO_COUNTRIES}
        selection, found = _selected(args, only, group=group_by, value=value)
        lines, previous = report.build_groups(selection, found)
        loaded = {kind: at.isoformat() for kind, at in read.last_loaded().items()}
    groups = [
        {
            "level": line.level,
            "key": line.key,
            "name": _group_name(line, selection, found),
            "countries": list(line.countries),
            "rs": _shown(line.rs),
            "rs_delta": line.rs_delta,
            "rko": _shown(line.rko),
            "rko_delta": line.rko_delta,
        }
        for line in lines
    ]
    empty = all(g["rs"] is None and g["rko"] is None for g in groups)
    return {
        "status": "no_data" if empty else "ok",
        "group_by": selection.group,
        "value": selection.value,
        "period": _period_json(selection.period),
        "previous_period": _period_json(previous),
        "groups": groups,
        "loaded_at": loaded,
        "scale": SCORE_NOTE,
        **({"message": NO_DATA} if empty else {}),
    }


def _limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if not 1 <= limit <= MAX_LIMIT:
        raise ToolError(f"limit: от 1 до {MAX_LIMIT}, получено {limit}")
    return limit


def _matches(unit: units_view.UnitView, *, city: str | None, name: str | None) -> bool:
    if city and city.strip().casefold() not in unit.name.casefold():
        return False
    if not name or not name.strip():
        return True
    wanted = name.strip().casefold()
    if len(wanted) == _HEX32_LEN and unit.unit == wanted:
        return True
    return wanted in unit.name.casefold()


def ratings_units(
    *,
    tenant: str,
    country: str | None = None,
    city: str | None = None,
    unit: str | None = None,
    period: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
) -> dict[str, object]:
    args = _period_args(period, date_from, date_to)
    cap = _limit(limit)
    with _ratings():
        only = _scope(tenant)
        if only == ():
            return {"status": "no_countries", "message": NO_COUNTRIES}
        group = report.GROUP_COUNTRY if country else report.GROUP_IMF
        selection, found = _selected(
            args, only, group=group, value=country.strip().upper() if country else None
        )
        codes = report.group_countries(selection, found.countries)
        until = min(selection.period.end, date.today())
        views = units_view.load(report.period_scores(selection, codes), codes, until=until)
    chosen = [v for v in views if _matches(v, city=city, name=unit)]
    page = chosen[:cap]
    return {
        "status": "ok" if chosen else "no_data",
        "period": _period_json(selection.period),
        "total": len(chosen),
        "returned": len(page),
        "truncated": len(chosen) > cap,
        "units": [
            {
                "unit_id": v.unit,
                "name": v.name,
                "country": v.country,
                "rs": _shown(v.rs),
                "rko": _shown(v.rko),
                "maps_google": None
                if v.maps is None
                else {"score": v.maps[0], "reviews": v.maps[1]},
                "aggregators": [
                    {
                        "aggregator": a.aggregator,
                        "score": a.score,
                        "scale": a.scale,
                        "votes": a.votes,
                        "as_of": a.on_date.isoformat(),
                    }
                    for a in v.aggregators
                ],
            }
            for v in page
        ],
        "scale": f"{SCORE_NOTE}. {AGG_NOTE}",
        **({} if chosen else {"message": NO_DATA + " или под отбор никто не попал"}),
    }


def aggregators_status(*, tenant: str) -> dict[str, object]:
    # Текст ошибки сбора на экране видит только контроль УК; партнёру — исход без текста.
    sees_errors = canonical_tenant(tenant) == HQ_TENANT
    with _ratings():
        states = {s.aggregator: s for s in agg_store.load_states()}
        pending = agg_store.open_request()
    rows = []
    for key, scale, by_bot in queue.listing():
        state = states.get(key)
        rows.append(
            {
                "aggregator": key,
                "scale": scale,
                "collected_by_bot": by_bot,
                "last_run_at": state.at.isoformat() if state else None,
                "outcome": state.outcome if state else "never_run",
                "points": state.points if state else 0,
                "error": state.error if state and sees_errors else None,
                "last_ok_at": state.last_ok.isoformat() if state and state.last_ok else None,
            }
        )
    return {
        "status": "ok",
        "aggregators": rows,
        "update_request": (
            None
            if pending is None
            else {
                "queued": True,
                "requested_at": pending.requested_at.isoformat(),
                "requested_by": pending.requested_by if sees_errors else None,
                "aggregators": list(pending.aggregators) or "all",
            }
        ),
        "schedule": "Бот собирает все агрегаторы раз в сутки; внеочередное обновление — по заявке",
        "scale": AGG_NOTE,
    }
