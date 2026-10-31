"""Data-owned semantic tags; all wording and codes below are synthetic."""

# ruff: noqa: F811
from __future__ import annotations

from test_web_walk_write import клиент  # noqa: F401

from src.domain.models import ChecklistItem
from src.recognize import cues
from src.web.walk_search_tags import search_tags

SYNTHETIC_CUES = """## Objects
| Object | Dirt | Labels | Candidates |
| --- | --- | --- | --- |
| Synthetic object | AAA01 | BBB02 | --- |
| Expired synthetic object | --- | --- | CCC03, OLD99 |
| Food segregation synthetic object | --- | --- | DDD04, INF05, AGG06, IIF08 |
"""


def item(code, *, kind="violation", question="Synthetic observation", levels=None):
    return ChecklistItem(
        code,
        kind,
        "Synthetic process",
        "Synthetic process",
        question,
        question,
        levels or ["D1"],
        ["zone_a"],
        0,
    )


def synthetic_catalogue():
    return [
        item("AAA01"),
        item("BBB02"),
        item("CCC03"),
        item("DDD04"),
        item("INF05", levels=["D0"]),
        item("AGG06", kind="aggregate"),
        item("IIF08", kind="info"),
        item("EXT07"),
        item("CLN99"),
        item("FSB99"),
    ]


def test_tags_use_distinct_columns_and_only_current_violation_codes(monkeypatch):
    reads = []
    monkeypatch.setattr(cues, "_read", lambda path, chat: reads.append(chat) or SYNTHETIC_CUES)
    result = search_tags(synthetic_catalogue(), chat_id=987)
    assert reads == [987]  # one pinned snapshot, no per-tag reads
    assert {t["id"]: t["codes"] for t in result} == {
        "dirty": ["AAA01"],
        "labels": ["BBB02"],
        "expired": ["CCC03"],
        "segregation": ["DDD04"],
    }


def test_fresh_snapshot_replaces_mapping_instead_of_caching_previous_codes(monkeypatch):
    content = [SYNTHETIC_CUES]
    monkeypatch.setattr(cues, "_read", lambda path, chat: content[0])
    assert search_tags(synthetic_catalogue(), chat_id=987)[0]["codes"] == ["AAA01"]
    content[0] = SYNTHETIC_CUES.replace("AAA01", "EXT07")
    assert search_tags(synthetic_catalogue(), chat_id=987)[0]["codes"] == ["EXT07"]


def test_without_cues_lookup_can_use_current_checklist_text_without_code_prefix_guess(monkeypatch):
    monkeypatch.setattr(cues, "_read", lambda path, chat: "")
    result = search_tags([item("XYZ01", question="Synthetic labels"), item("CLN99")], chat_id=987)
    assert {t["id"]: t["codes"] for t in result} == {
        "dirty": [],
        "labels": ["XYZ01"],
        "expired": [],
        "segregation": [],
    }


def test_signed_payload_uses_one_pinned_lookup_and_keeps_manual_catalogue(клиент, monkeypatch):
    from src.web import walk

    reads = []
    monkeypatch.setattr(cues, "_read", lambda path, chat: reads.append(chat) or SYNTHETIC_CUES)
    monkeypatch.setattr(walk, "list_items", lambda **kwargs: synthetic_catalogue())
    response = клиент.c.post(walk.DATA_PATH, data=клиент.init, content_type="text/plain")
    assert response.status_code == 200
    payload = response.get_json()
    assert len(reads) == 1 and reads[0] is not None
    assert {tag["id"]: tag["codes"] for tag in payload["item_search_tags"]} == {
        "dirty": ["AAA01"],
        "labels": ["BBB02"],
        "expired": ["CCC03"],
        "segregation": ["DDD04"],
    }
    assert {item["code"] for item in payload["items"]} == {
        "AAA01",
        "BBB02",
        "CCC03",
        "DDD04",
        "INF05",
        "EXT07",
        "CLN99",
        "FSB99",
    }
