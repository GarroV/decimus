"""Оценки на картах поштучно: загрузка из Pointer `/reviews` и сверка со счётчиком карточки.

D732, D733, #1562. Карта в «Качестве» считается по оценкам, поставленным за месяц
(`domain/maps_month.py`), поэтому нужны сами оценки, а не общий счётчик карточки.

**Что грузим.** Набор карт — `pointer.MAP_PROVIDERS`. Пара «связанный филиал × карта» сначала
заливается за `HISTORY_MONTHS` месяцев (с первого числа месяца, чтобы месяцы были полными), потом
раз в сутки догружаются два последних месяца: так ловятся правки и удаления. Что уже легло,
знает база (`maps.reviews_sync`): прерванная загрузка продолжается с места.

**Сверка.** Число неудалённых оценок в выгрузке против прироста счётчика карточки за то же
время. Расхождение — в данных (вывод команды `python -m src.ratings.maps reconcile`, строка в
логе бота); никаких рассылок (D733, п. 4).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.db import maps_reviews_store as store
from src.domain.maps_month import shift_month

from . import pointer

logger = logging.getLogger(__name__)

#: Глубина истории «Качества» (D733, п. 8): столько полных месяцев до текущего.
HISTORY_MONTHS = 12
#: Сколько последних месяцев догружается каждый день (правки и удаления).
TOP_UP_MONTHS = 2


def _provider_ids() -> tuple[int, ...]:
    return tuple(p.id for p in pointer.MAP_PROVIDERS)


@dataclass(frozen=True)
class ReviewsStep:
    """Итог шага: сколько оценок легло, запросов ушло, всё ли на сегодня закрыто."""

    saved: int
    requests: int
    done: bool


def history_start(today: date) -> date:
    """Первое число месяца, с которого заливается история."""
    return shift_month(today.replace(day=1), -HISTORY_MONTHS)


def _plan(state: store.SyncState, today: date) -> tuple[date, bool] | None:
    """Что нужно паре сегодня: `(с какой даты, это заливка истории)` или `None` — всё есть."""
    start = history_start(today)
    if state.backfilled_from is None or state.backfilled_from > start:
        return start, True
    if state.topped_up_on is None or state.topped_up_on < today:
        return shift_month(today.replace(day=1), -(TOP_UP_MONTHS - 1)), False
    return None


def reviews_step(
    *, today: date, fetch: pointer.Fetch, max_requests: int | None = None
) -> ReviewsStep:
    """Один шаг загрузки оценок: не больше `max_requests` запросов к Pointer за шаг.

    Пара записывается целиком одной транзакцией, поэтому прерывание между парами безопасно."""
    requests = 0

    def counted(path: str) -> Mapping[str, Any]:
        nonlocal requests
        requests += 1
        return fetch(path)

    saved = 0
    for state in store.sync_states(_provider_ids()):
        plan = _plan(state, today)
        if plan is None:
            continue
        if max_requests is not None and requests >= max_requests:
            return ReviewsStep(saved, requests, done=False)
        start, backfill = plan
        found = pointer.reviews(counted, state.company_uuid, state.provider_id, start, today)
        rows = [
            (r.id, state.company_uuid, r.provider_id, r.rating, r.published_at, r.is_deleted)
            for r in found
        ]
        saved += store.save_reviews(
            rows,
            company_uuid=state.company_uuid,
            provider_id=state.provider_id,
            start=start,
            end=today,
            today=today,
            backfill=backfill,
        )
    return ReviewsStep(saved, requests, done=True)


@dataclass(frozen=True)
class Mismatch:
    """Карточка, у которой выгрузка и счётчик расходятся."""

    company_uuid: str
    provider_id: int
    ours: int
    counter_delta: int

    @property
    def diff(self) -> int:
        """Положительное — в выгрузке больше, чем прибавил счётчик."""
        return self.ours - self.counter_delta


def reconcile_counts(cards: Sequence[store.CardCounts]) -> tuple[tuple[Mismatch, ...], int]:
    """Расхождения и число карточек, которые не с чем сверять (нет снимка до начала истории)."""
    mismatches: list[Mismatch] = []
    unchecked = 0
    for card in cards:
        if card.counter_before is None:
            unchecked += 1
            continue
        delta = card.counter_now - card.counter_before
        if card.ours != delta:
            mismatches.append(Mismatch(card.company_uuid, card.provider_id, card.ours, delta))
    mismatches.sort(key=lambda m: (-abs(m.diff), m.company_uuid, m.provider_id))
    return tuple(mismatches), unchecked


def reconcile() -> tuple[tuple[Mismatch, ...], int, int]:
    """Сверка по всем загруженным карточкам: `(расхождения, не с чем сверять, всего карточек)`."""
    cards = store.card_counts(_provider_ids())
    mismatches, unchecked = reconcile_counts(cards)
    return mismatches, unchecked, len(cards)


def report(mismatches: Sequence[Mismatch], unchecked: int, total: int, *, limit: int = 30) -> str:
    """Сверка словами для вывода команды и лога."""
    names = {p.id: p.name for p in pointer.MAP_PROVIDERS}
    lines = [
        f"Сверка оценок карт: карточек {total}, расходятся {len(mismatches)}, "
        f"сверить не с чем {unchecked}"
    ]
    for m in mismatches[:limit]:
        lines.append(
            f"  {m.company_uuid} {names.get(m.provider_id, m.provider_id)}: "
            f"в выгрузке {m.ours}, счётчик прибавил {m.counter_delta} ({m.diff:+d})"
        )
    if len(mismatches) > limit:
        lines.append(f"  … и ещё {len(mismatches) - limit}")
    return "\n".join(lines)
