"""The walk split endpoint shares the domain's atomic confirmation and replay contract."""

from __future__ import annotations

from dataclasses import asdict

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import ДРУГОЙ_JPEG, Клиент, _нарушение, клиент  # noqa: F401

from src.domain import get_state
from src.domain.config import check_environment
from src.domain.engine import state_file
from src.domain.errors import EngineError
from src.domain.split import SplitPart, finding_revision


def payload(client: Клиент):
    a, b = client.ссылка(), client.ссылка(ДРУГОЙ_JPEG)
    assert (
        client.запись(**_нарушение(a, photos=[a, b], text="Combined synthetic finding")).status_code
        == 200
    )
    inspection = get_state(АУДИТОР)
    source = inspection.findings[0]
    return dict(
        op="split",
        n=source.n,
        run_id=inspection.run_id,
        source_revision=finding_revision(source),
        request_id="a" * 32,
        confirmed=True,
        shared_photos=[],
        parts=[
            asdict(SplitPart("CLN05", "D1", "hot_kitchen", "One", photos=(a,))),
            asdict(SplitPart("CLN06", "D1", "hot_kitchen", "Two", photos=(b,))),
        ],
    )


def test_walk_split_updates_all_parts_and_history_once(клиент: Клиент) -> None:  # noqa: F811
    body = payload(клиент)
    first = клиент.запись(**body)
    assert first.status_code == 200
    assert len(first.get_json()["finding_history"]) == 1
    assert len(get_state(АУДИТОР).findings) == 2
    retry = клиент.запись(**body)
    assert retry.status_code == 200
    assert retry.get_json()["finding_history"] == first.get_json()["finding_history"]


@pytest.mark.parametrize("bad", ["no-run", "unconfirmed", "stale-revision"])
def test_split_does_not_accept_missing_confirmation_or_stale_source(
    клиент: Клиент,  # noqa: F811
    bad: str,
) -> None:
    body = payload(клиент)
    if bad == "no-run":
        body.pop("run_id")
    if bad == "unconfirmed":
        body["confirmed"] = False
    if bad == "stale-revision":
        body["source_revision"] = "0" * 64
    path = state_file(АУДИТОР, check_environment())
    before = path.read_bytes()
    reply = клиент.запись(**body)
    assert reply.status_code == (409 if bad == "stale-revision" else 422)
    assert path.read_bytes() == before


def test_walk_split_failure_rolls_back_source_and_history(
    клиент: Клиент,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.domain import split

    body = payload(клиент)
    path = state_file(АУДИТОР, check_environment())
    before = path.read_bytes()
    real = split.run_audit
    count = 0

    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 3:
            raise EngineError("synthetic refusal", code=1, command="add")
        return real(*args, **kwargs)

    monkeypatch.setattr(split, "run_audit", fail_second)
    assert клиент.запись(**body).status_code == 422
    assert path.read_bytes() == before
