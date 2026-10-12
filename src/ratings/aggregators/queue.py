"""Заявка на обновление оценок агрегаторов вне расписания (D420).

Просьбу принимает веб (кнопка) или MCP (`request_aggregators_update`), а собирает
бот: сбор живёт в одном процессе, второго места, где он идёт, нет (D389). Здесь —
общая сторона: принять просьбу (`ask`) и выполнить принятую (`fulfil`). Таблица —
`agg.requests`, миграция 0053.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from src.db import agg_store
from src.db.agg_store import UpdateRequest

from . import collect

logger = logging.getLogger(__name__)

#: Как часто бот заглядывает в таблицу заявок (в секундах): только в неё, а не
#: в журнал сбора — это один дешёвый запрос.
POLL_EVERY_SEC = 60
ERROR_LIMIT = 500


class UnknownAggregator(ValueError):
    """Названного агрегатора бот не собирает."""


@dataclass(frozen=True)
class Asked:
    request: UpdateRequest
    #: `True` — заявка принята сейчас; `False` — такая уже стояла в очереди.
    created: bool


def known_keys() -> tuple[str, ...]:
    """Агрегаторы, которые бот собирает сам, — их и можно просить обновить."""
    return tuple(m.KEY for m in collect.SEARCHERS + collect.KNOWN)


def listing() -> tuple[tuple[str, int, bool], ...]:
    """Все известные агрегаторы: (ключ, шкала оценки, собирает ли его бот сам).
    Шкала — родная агрегатора: 10, 100 (% довольных) или 5."""
    every = collect.SEARCHERS + collect.KNOWN + collect.PAUSED
    return tuple((m.KEY, m.SCALE, m not in collect.PAUSED) for m in every)


def ask(aggregators: Sequence[str] | None, *, by: str) -> Asked:
    """Поставить заявку. `None` или пусто — все агрегаторы. Незнакомое имя —
    `UnknownAggregator`; база не ответила — `RatingsError`."""
    wanted = tuple(dict.fromkeys(a.strip().lower() for a in aggregators or () if a.strip()))
    known = known_keys()
    unknown = [a for a in wanted if a not in known]
    if unknown:
        raise UnknownAggregator(
            f"Агрегатор не из списка: {', '.join(unknown)}. Есть: {', '.join(known)}"
        )
    request, created = agg_store.request_update(wanted, by=by)
    return Asked(request, created)


def _result(outcomes: Sequence[collect.Outcome]) -> tuple[bool, str | None]:
    failed = [o for o in outcomes if not o.ok]
    if not failed:
        return True, None
    text = "; ".join(f"{o.aggregator}: {o.error or 'сбой'}" for o in failed)
    return False, text[:ERROR_LIMIT]


def fulfil(*, today: date, run: Callable[..., Sequence[collect.Outcome]] | None = None) -> bool:
    """Выполнить стоящую в очереди заявку: собрать названных (или всех) и закрыть
    её исходом. `False` — очередь пуста. Сбой самого сбора заявку закрывает как
    неудавшуюся — иначе она вернулась бы в бота каждую минуту."""
    request = agg_store.open_request()
    if request is None:
        return False
    collector = run or collect.run_all
    try:
        outcomes = collector(today, only=request.aggregators)
        ok, error = _result(outcomes)
    except Exception as exc:  # заявка не должна висеть из-за сбоя сборщика
        logger.exception("Заявка на обновление агрегаторов №%s: сбор упал", request.id)
        ok, error = False, f"{type(exc).__name__}"
    agg_store.finish_request(request.id, ok=ok, error=error)
    return True
