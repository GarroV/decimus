"""Photo ownership is checked independently of untrusted evidence metadata."""

# ruff: noqa: F811
from __future__ import annotations

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import ДРУГОЙ_JPEG, Клиент, клиент  # noqa: F401

from src.domain import get_state, start_inspection
from src.web import walk_write


def assignment(source, assigned, model=None):
    return {
        "source_photos": source,
        "model_source_photos": source,
        "model_frame_indices": model,
        "assigned_frame_indices": assigned,
        "confirmed": True,
    }


def add(client, refs, metadata, **extra):
    return client.запись(
        op="add",
        code="CLN05",
        level="D1",
        zone="hot_kitchen",
        text="Synthetic fact",
        photos=refs,
        photo_assignment=metadata,
        **extra,
    )


def test_two_candidates_save_only_their_explicit_photos(клиент, monkeypatch):
    first, second = клиент.ссылка(), клиент.ссылка(ДРУГОЙ_JPEG)
    events = []
    monkeypatch.setattr(
        walk_write.journal, "note", lambda chat, event, **kw: events.append((event, kw))
    )
    assert add(клиент, [first], assignment([first, second], [0], [1])).status_code == 200
    response = клиент.запись(
        op="add",
        code="CLN05",
        level="D1",
        zone="dining",
        text="Synthetic second fact",
        photos=[second],
        also=True,
        photo_assignment=assignment([first, second], [1], [0]),
    )
    assert response.status_code == 200, response.get_json()
    findings = get_state(АУДИТОР).findings
    assert [f.photos for f in findings] == [[first], [second]]
    recorded = [kw for event, kw in events if event == "walk_photo_assignment"]
    assert [(r["model_frame_indices"], r["assigned_frame_indices"]) for r in recorded] == [
        ([1], [0]),
        ([0], [1]),
    ]


@pytest.mark.parametrize("indices", [None, [], [True], [1.0], [2], [-1], [0, 0]])
def test_invalid_or_missing_human_assignment_cannot_save(клиент, indices):
    ref = клиент.ссылка()
    response = add(клиент, [ref], assignment([ref], indices), also=True)
    assert response.status_code == 422
    assert get_state(АУДИТОР).findings == []


def test_no_all_photos_fallback_for_legacy_extra(клиент):
    ref = клиент.ссылка()
    response = add(клиент, [ref], None, also=True)
    assert response.status_code == 422
    assert get_state(АУДИТОР).findings == []


def test_unconfirmed_or_stale_ref_mapping_cannot_save(клиент):
    first, second = клиент.ссылка(), клиент.ссылка(ДРУГОЙ_JPEG)
    data = assignment([first, second], [0], [0])
    data["confirmed"] = False
    assert add(клиент, [first], data).status_code == 422
    data["confirmed"] = True
    assert add(клиент, [second], data).status_code == 422
    assert get_state(АУДИТОР).findings == []


def test_model_metadata_never_grants_ownership(клиент):
    own = клиент.ссылка()
    start_inspection(777, unit="Synthetic unit", kind="planned", report_lang="ru", ui_lang="ru")
    foreign = Клиент(клиент.c, 777).ссылка(ДРУГОЙ_JPEG)
    data = assignment([own], [0], [0])
    data["model_source_photos"] = [foreign]
    response = add(клиент, [own], data)
    assert response.status_code == 422
    assert get_state(АУДИТОР).findings == []


def test_journal_failure_does_not_turn_success_into_a_retry(клиент, monkeypatch):
    ref = клиент.ссылка()

    def fail(*args, **kwargs):
        raise OSError("synthetic audit failure")

    monkeypatch.setattr(walk_write.journal, "note", fail)
    response = add(клиент, [ref], assignment([ref], [0], [0]))
    assert response.status_code == 200, response.get_json()
    assert len(get_state(АУДИТОР).findings) == 1


def test_attach_checks_mapping_before_mutation_and_records_assignment(клиент, monkeypatch):
    first, second = клиент.ссылка(), клиент.ссылка(ДРУГОЙ_JPEG)
    assert add(клиент, [first], None).status_code == 200
    events = []
    monkeypatch.setattr(
        walk_write.journal, "note", lambda chat, event, **kw: events.append((event, kw))
    )
    wrong = assignment([first, second], [0], [0])
    response = клиент.запись(op="attach", n=1, ref=second, photo_assignment=wrong)
    assert response.status_code == 422
    assert get_state(АУДИТОР).findings[0].photos == [first]
    correct = assignment([first, second], [1], [0])
    response = клиент.запись(op="attach", n=1, ref=second, photo_assignment=correct)
    assert response.status_code == 200
    assert get_state(АУДИТОР).findings[0].photos == [first, second]
    event = next(kw for name, kw in events if name == "walk_photo_assignment")
    assert event["n"] == 1 and event["assigned_frame_indices"] == [1]
    assert event["model_frame_indices"] == [0]


@pytest.mark.parametrize("model_indices", [[True], [1.0], [1], [-1], [0, 0]])
def test_untrusted_invalid_model_proposal_is_not_accepted_as_metadata(клиент, model_indices):
    ref = клиент.ссылка()
    response = add(клиент, [ref], assignment([ref], [0], model_indices), also=True)
    assert response.status_code == 422
    assert get_state(АУДИТОР).findings == []
