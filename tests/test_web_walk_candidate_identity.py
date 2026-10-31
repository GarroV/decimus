"""One code in two resolved zones means two candidates, not a duplicate."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.bot.propose import Offer
from src.recognize.models import UNKNOWN_ZONE, Candidate, Suggestion
from src.web import walk_suggest


def candidate(zone, wording="Synthetic fact"):
    return Candidate("SYN01", "D1", zone, wording, 0.9)


@pytest.fixture
def ask(monkeypatch):
    monkeypatch.setattr(walk_suggest, "allowed_zones", lambda *a, **kw: ("zone_a", "zone_b"))
    return walk_suggest.Ask(chat_id=1, spoken=None, hint=None)


def test_same_code_different_resolved_zones_survive(ask):
    offer = Offer("model", (candidate("zone_a"),), also_seen=(candidate("zone_b"),))
    cards = walk_suggest.answer(offer, ask)["candidates"]
    assert [(c["code"], c["resolution"]["zone"]) for c in cards] == [
        ("SYN01", "zone_a"),
        ("SYN01", "zone_b"),
    ]


def test_dedup_uses_resolved_zone_and_preserves_raw_model_zone(ask):
    offer = Offer("model", (candidate("zone_b"),), also_seen=(candidate("zone_a"),))
    cards = walk_suggest.answer(offer, replace(ask, spoken="zone_a"))["candidates"]
    assert len(cards) == 1
    assert cards[0]["zone"] == "zone_b"
    assert cards[0]["resolution"]["zone"] == "zone_a"


def test_unknown_zones_remain_distinct_candidates(ask):
    offer = Offer(
        "model",
        (candidate(UNKNOWN_ZONE, "Synthetic first"),),
        also_seen=(candidate(UNKNOWN_ZONE, "Synthetic second"),),
    )
    cards = walk_suggest.answer(offer, ask)["candidates"]
    assert [c["wording"] for c in cards] == ["Synthetic first", "Synthetic second"]
    assert all(c["resolution"]["zone"] is None for c in cards)


def test_known_pair_duplicates_are_removed_without_reordering(ask):
    first, second = candidate("zone_a"), candidate("zone_b")
    cue = replace(second, confidence=0.0)
    suggestion = Suggestion(cue_extras=(cue,))
    offer = Offer("model", (first,), also_seen=(first, second, second), suggestion=suggestion)
    cards = walk_suggest.answer(offer, replace(ask, hint="zone_b"))["candidates"]
    assert [c["resolution"]["zone"] for c in cards] == ["zone_a", "zone_b"]
