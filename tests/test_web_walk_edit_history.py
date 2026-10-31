"""Authenticated HTTP edits commit all evidence together and reject stale revisions."""

from test_web_walk import АУДИТОР
from test_web_walk_write import ДРУГОЙ_JPEG, Клиент, _нарушение, клиент  # noqa: F401

from src.domain import get_state
from src.domain.revisions import finding_revision


def test_edit_atomic_photos_reading_replay_and_stale(клиент: Клиент):  # noqa: F811
    first = клиент.ссылка()
    second = клиент.ссылка(ДРУГОЙ_JPEG)
    assert клиент.запись(**_нарушение(first)).status_code == 200
    original = get_state(АУДИТОР).findings[0]
    body = dict(
        op="edit",
        n=original.n,
        source_revision=finding_revision(original),
        request_id="e" * 32,
        text="Synthetic changed",
        reading_c=0,
        new_refs=[second],
        remove_photos=[first],
    )
    reply = клиент.запись(**body)
    assert reply.status_code == 200, reply.get_json()
    assert клиент.запись(**body).status_code == 200
    state = get_state(АУДИТОР)
    assert len(state.finding_history) == 1
    assert state.findings[0].photos == [second]
    assert state.findings[0].reading_c == 0
    assert клиент.запись(**(body | {"request_id": "f" * 32, "text": "Stale"})).status_code == 409
    assert get_state(АУДИТОР) == state


def test_unowned_upload_and_last_photo_failure_keep_fields(клиент: Клиент):  # noqa: F811
    first = клиент.ссылка()
    клиент.запись(**_нарушение(first))
    before = get_state(АУДИТОР)
    n = before.findings[0].n
    assert (
        клиент.запись(op="edit", n=n, text="Must rollback", remove_photos=[first]).status_code
        == 422
    )
    assert get_state(АУДИТОР) == before
    assert (
        клиент.запись(op="edit", n=n, text="Must not write", new_refs=["bad-ref"]).status_code
        == 422
    )
    assert get_state(АУДИТОР) == before
