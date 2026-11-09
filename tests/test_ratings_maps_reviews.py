"""Оценки карт поштучно (#1562): разбор ответа Pointer, ход загрузки, сверка со счётчиком.

Pointer и база подменены: живой Pointer в тестах не трогаем. Проверяется порядок работы —
что запрашивается, когда пара считается загруженной, что попадает в запись.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.bot import maps_loader
from src.db import maps_reviews_store as store
from src.ratings import maps_reviews, pointer

СЕГОДНЯ = date(2026, 11, 9)
ФИЛИАЛ = "11111111-1111-1111-1111-111111111111"


def _отзыв(
    i: int, rating: object = 5, published: str = "2026-10-05T10:00:00Z", **extra: Any
) -> dict:
    return {"id": i, "rating": rating, "published_at": published, "is_deleted": False, **extra}


def _fetch(pages: list[list[dict]], calls: list[str]) -> pointer.Fetch:
    def fetch(path: str) -> dict[str, Any]:
        calls.append(path)
        n = len(calls) - 1
        return {"items": pages[n], "meta": {"total": sum(len(p) for p in pages)}}

    return fetch


def test_reviews_are_requested_with_plain_dates_and_parsed() -> None:
    calls: list[str] = []
    fetch = _fetch([[_отзыв(1, 4), _отзыв(2, 5, is_deleted=True)]], calls)
    got = pointer.reviews(fetch, ФИЛИАЛ, pointer.GOOGLE, date(2026, 9, 1), date(2026, 11, 9))
    assert "published_at_from=2026-09-01&published_at_to=2026-11-09" in calls[0]
    assert "T00:00" not in calls[0]  # со временем Pointer отвечает 400
    assert f"company_uuids={ФИЛИАЛ}&provider_ids=2" in calls[0]
    assert {(r.id, r.rating, r.published_at, r.is_deleted) for r in got} == {
        ("1", 4, date(2026, 10, 5), False),
        ("2", 5, date(2026, 10, 5), True),
    }


def test_broken_reviews_are_dropped_not_fatal() -> None:
    bad = [_отзыв(1, 0), _отзыв(2, "5"), _отзыв(3, 5, "вчера"), {"rating": 5}, _отзыв(4, 3)]
    got = pointer.reviews(_fetch([bad], []), ФИЛИАЛ, 2, date(2026, 10, 1), date(2026, 10, 31))
    assert [r.id for r in got] == ["4"]


class _Склад:
    """Подмена записи и хода загрузки в базе."""

    def __init__(self, states: list[store.SyncState]) -> None:
        self.states = states
        self.saved: list[dict[str, Any]] = []

    def sync_states(self, _providers: object) -> tuple[store.SyncState, ...]:
        return tuple(self.states)

    def save_reviews(self, rows: list, **kw: Any) -> int:
        self.saved.append({"rows": rows, **kw})
        return len(rows)


@pytest.fixture
def склад(monkeypatch: pytest.MonkeyPatch) -> _Склад:
    s = _Склад([])
    monkeypatch.setattr(store, "sync_states", s.sync_states)
    monkeypatch.setattr(store, "save_reviews", s.save_reviews)
    return s


def _пусто(_path: str) -> dict[str, Any]:
    return {"items": [], "meta": {"total": 0}}


def test_new_pair_gets_twelve_full_months_then_only_two_last_months(склад: _Склад) -> None:
    склад.states = [
        store.SyncState(ФИЛИАЛ, 2, None, None),  # не грузили
        store.SyncState(ФИЛИАЛ, 1, date(2025, 11, 1), date(2026, 11, 8)),  # вчера догружали
    ]
    step = maps_reviews.reviews_step(today=СЕГОДНЯ, fetch=_пусто)
    assert step.done
    assert [(x["provider_id"], x["start"], x["backfill"]) for x in склад.saved] == [
        (2, date(2025, 11, 1), True),
        (1, date(2026, 10, 1), False),
    ]


def test_pair_loaded_today_is_not_requested_again(склад: _Склад) -> None:
    склад.states = [store.SyncState(ФИЛИАЛ, 2, date(2025, 11, 1), СЕГОДНЯ)]
    step = maps_reviews.reviews_step(today=СЕГОДНЯ, fetch=_пусто)
    assert (step.requests, step.done, склад.saved) == (0, True, [])


def test_step_stops_at_request_budget_and_resumes_from_database(склад: _Склад) -> None:
    склад.states = [store.SyncState(ФИЛИАЛ, p, None, None) for p in (1, 2)]
    step = maps_reviews.reviews_step(today=СЕГОДНЯ, fetch=_пусто, max_requests=1)
    assert (step.requests, step.done, len(склад.saved)) == (1, False, 1)


def test_reconcile_compares_reviews_with_counter_growth_over_same_period() -> None:
    cards = [
        store.CardCounts("a", 2, date(2025, 11, 1), ours=40, counter_now=140, counter_before=100),
        store.CardCounts("b", 2, date(2025, 11, 1), ours=30, counter_now=140, counter_before=100),
        store.CardCounts("c", 1, date(2025, 11, 1), ours=5, counter_now=5, counter_before=None),
    ]
    mismatches, unchecked = maps_reviews.reconcile_counts(cards)
    assert [(m.company_uuid, m.diff) for m in mismatches] == [("b", -10)]
    assert unchecked == 1
    text = maps_reviews.report(mismatches, unchecked, 3)
    assert "расходятся 1" in text and "в выгрузке 30, счётчик прибавил 40" in text


def test_reviews_cycle_reconciles_once_a_day_only_when_everything_is_loaded(
    склад: _Склад, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(maps_loader, "_today", lambda: СЕГОДНЯ)
    runs: list[int] = []
    monkeypatch.setattr(maps_reviews, "reconcile", lambda: (runs.append(1) or (), 0, 0))
    state = maps_loader.ReviewsState()
    склад.states = [store.SyncState(ФИЛИАЛ, 2, None, None)]
    assert maps_loader.reviews_cycle(state, fetch=_пусто)
    assert maps_loader.reviews_cycle(state, fetch=_пусто)
    assert runs == [1]  # второй круг того же дня сверку не повторяет
