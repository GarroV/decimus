"""Оценки карт поштучно в базе (миграция 0127, #1562): запись, пометка исчезнувших, месячные суммы.

Идёт на тестовой базе MUSPELHEIM (`requires_db`).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from conftest import requires_db

psycopg = pytest.importorskip("psycopg")

from src.db import maps_reviews_store as store  # noqa: E402

pytestmark = requires_db

UNIT = "d" * 32
TODAY = date(2026, 11, 9)


@pytest.fixture
def card(db_env: str) -> tuple[str, str]:
    """Связанный филиал и снятый филиал той же пиццерии."""
    linked, excluded = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(db_env) as conn:
        for cid, reason in ((linked, None), (excluded, "закрыт")):
            conn.execute(
                "insert into maps.companies (uuid, name, country_code, dodo_id, excluded_reason) "
                "values (%s, 'x', 'AA', %s, %s)",
                (cid, UNIT, reason),
            )
    return linked, excluded


def _rows(card_id: str, items: list[tuple[str, int, date, bool]]) -> list:
    return [(rid, card_id, 2, rating, day, deleted) for rid, rating, day, deleted in items]


def _save(card_id: str, items: list, *, start: date, backfill: bool) -> None:
    store.save_reviews(
        _rows(card_id, items),
        company_uuid=card_id,
        provider_id=2,
        start=start,
        end=TODAY,
        today=TODAY,
        backfill=backfill,
    )


def test_monthly_sums_skip_deleted_and_excluded_and_group_by_publication_month(
    card: tuple[str, str],
) -> None:
    linked, excluded = card
    _save(
        linked,
        [
            ("r1", 5, date(2026, 10, 3), False),
            ("r2", 3, date(2026, 10, 30), False),
            ("r3", 1, date(2026, 10, 31), True),  # удалена — не считается
            ("r4", 4, date(2026, 9, 1), False),
        ],
        start=date(2025, 11, 1),
        backfill=True,
    )
    _save(excluded, [("r9", 1, date(2026, 10, 4), False)], start=date(2025, 11, 1), backfill=True)

    stats = store.monthly_stats(2, until=TODAY)

    assert stats.by_unit[UNIT] == {
        date(2026, 10, 1): (2, 8),
        date(2026, 9, 1): (1, 4),
    }
    assert stats.floor == date(2025, 11, 1)


def test_review_missing_from_a_fresh_window_is_marked_deleted_and_edits_apply(
    card: tuple[str, str],
) -> None:
    linked, _ = card
    _save(
        linked,
        [("r1", 5, date(2026, 10, 3), False), ("r2", 4, date(2026, 10, 9), False)],
        start=date(2025, 11, 1),
        backfill=True,
    )
    # догрузка двух последних месяцев: r2 исчезла, r1 исправлена на 2 звезды
    _save(linked, [("r1", 2, date(2026, 10, 3), False)], start=date(2026, 10, 1), backfill=False)

    stats = store.monthly_stats(2, until=TODAY)
    assert stats.by_unit[UNIT] == {date(2026, 10, 1): (1, 2)}
    sync = {s.company_uuid: s for s in store.sync_states([2])}[linked]
    assert (sync.backfilled_from, sync.topped_up_on) == (date(2025, 11, 1), TODAY)


def test_card_counts_give_reconciliation_inputs(db_env: str, card: tuple[str, str]) -> None:
    linked, _ = card
    with psycopg.connect(db_env) as conn:
        for day, count in ((date(2025, 10, 20), 100), (date(2026, 11, 8), 130)):
            conn.execute(
                "insert into maps.ratings (company_uuid, provider_id, on_date, avg_rating, "
                "ratings_count) values (%s, 2, %s, 4.5, %s)",
                (linked, day, count),
            )
    _save(linked, [("r1", 5, date(2026, 10, 3), False)], start=date(2025, 11, 1), backfill=True)

    got = [c for c in store.card_counts([2]) if c.company_uuid == linked]

    assert got == [store.CardCounts(linked, 2, date(2025, 11, 1), 1, 130, 100)]
