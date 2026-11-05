"""Learned phrases handed to the walk screen: live only, bounded, current language."""

# ruff: noqa: F811
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from test_web_walk_search_tags import SYNTHETIC_CUES, synthetic_catalogue
from test_web_walk_write import клиент  # noqa: F401

from src.db.errors import DbError
from src.db.synonyms import PhraseAlias
from src.recognize import cues
from src.web import walk, walk_aliases

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def alias(code, phrase, age=0, *, retracted=False, lang="ru"):
    return PhraseAlias(
        item_code=code,
        lang=lang,
        phrase=phrase,
        key=phrase.lower(),
        origin="learned",
        created_at=NOW - timedelta(days=age),
        retracted_at=NOW if retracted else None,
    )


def inspection():
    return SimpleNamespace(speech_lang="ru", tenant="hq")


def test_live_phrases_only_for_listed_codes_newest_first(monkeypatch):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return [alias("AAA01", "old", age=5), alias("AAA01", "new", age=1), alias("ZZZ99", "x")]

    monkeypatch.setattr(walk_aliases.synonyms, "list_phrases", fake)
    result = walk_aliases.item_aliases(inspection(), ["AAA01", "BBB02"])
    assert result == {"AAA01": ["new", "old"]}
    assert seen["lang"] == "ru" and "include_retracted" not in seen


def test_retracted_phrase_is_never_handed_out_even_if_the_map_returns_it(monkeypatch):
    rows = [alias("AAA01", "kept"), alias("AAA01", "taken down", retracted=True)]
    monkeypatch.setattr(walk_aliases.synonyms, "list_phrases", lambda **kw: rows)
    assert walk_aliases.item_aliases(inspection(), ["AAA01"]) == {"AAA01": ["kept"]}


def test_phrases_are_capped_per_item_and_trimmed(monkeypatch):
    rows = [alias("AAA01", f"phrase {n}", age=n) for n in range(40)]
    rows.append(alias("BBB02", "x" * 500, age=0))
    monkeypatch.setattr(walk_aliases.synonyms, "list_phrases", lambda **kw: rows)
    result = walk_aliases.item_aliases(inspection(), ["AAA01", "BBB02"])
    assert len(result["AAA01"]) == walk_aliases.MAX_PER_ITEM
    assert result["AAA01"][0] == "phrase 0"
    assert len(result["BBB02"][0]) == walk_aliases.MAX_LENGTH


def test_unavailable_map_gives_empty_dictionary_not_a_failed_screen(monkeypatch):
    def broken(**kw):
        raise DbError("down")

    monkeypatch.setattr(walk_aliases.synonyms, "list_phrases", broken)
    assert walk_aliases.item_aliases(inspection(), ["AAA01"]) == {}


def test_signed_payload_carries_item_aliases(клиент, monkeypatch):
    monkeypatch.setattr(cues, "_read", lambda path, chat: SYNTHETIC_CUES)
    monkeypatch.setattr(walk, "list_items", lambda **kwargs: synthetic_catalogue())
    monkeypatch.setattr(
        walk_aliases.synonyms,
        "list_phrases",
        lambda **kw: [alias("AAA01", "grimy tiles"), alias("AAA01", "gone", retracted=True)],
    )
    response = клиент.c.post(walk.DATA_PATH, data=клиент.init, content_type="text/plain")
    assert response.status_code == 200
    assert response.get_json()["item_aliases"] == {"AAA01": ["grimy tiles"]}
