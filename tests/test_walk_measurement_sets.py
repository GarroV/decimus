"""Authenticated persisted set operations and stale in-flight model response rejection."""

# ruff: noqa: F811
from copy import deepcopy

from test_walk_level import body, model, post  # noqa: F401
from test_web_walk import АУДИТОР
from test_web_walk_write import клиент  # noqa: F401

from src.domain import add_finding, get_state, set_reading
from src.domain.measurement_sets import public_sets
from src.domain.revisions import finding_revision
from src.recognize.classify import AskArgs
from src.recognize.client import ModelAnswer


def data():
    finding = add_finding(АУДИТОР, "INF10", "D0", "hot_kitchen", "Product reading", reading_c=2)
    return dict(
        schema=1,
        id="a" * 32,
        revision=None,
        code="CLN05",
        zone="hot_kitchen",
        line_label="Confirmed line",
        confirmed=True,
        products=[
            dict(
                id="b" * 32,
                label="Confirmed product",
                facts="",
                confirmed_product=True,
                sources=[dict(n=finding.n, revision=finding_revision(finding))],
            )
        ],
    )


def test_persist_delete_stale_write_and_foreign_run(клиент):
    value = data()
    run = get_state(АУДИТОР).run_id

    def write(value, **kw):
        return клиент.запись(op="measurement_set", measurement_set=value, run_id=run, **kw)

    assert write(value).status_code == 200
    saved = public_sets(get_state(АУДИТОР))[0]
    assert saved["revision"] and not saved["stale"]
    changed = deepcopy(value)
    changed["line_label"] = "Changed line"
    assert write(changed).status_code == 409
    assert (
        клиент.запись(op="measurement_set", measurement_set=value, run_id="foreign").status_code
        == 409
    )
    assert write({"id": saved["id"], "revision": saved["revision"]}, delete=True).status_code == 200
    assert get_state(АУДИТОР).measurement_sets == {}


def test_changed_measurement_during_model_call_is_not_returned_ready(клиент, model, monkeypatch):
    value = data()
    assert (
        клиент.запись(
            op="measurement_set", measurement_set=value, run_id=get_state(АУДИТОР).run_id
        ).status_code
        == 200
    )
    saved = public_sets(get_state(АУДИТОР))[0]

    def call(_):
        set_reading(АУДИТОР, 1, 3)
        return ModelAnswer(dict(level="D1", need_fact="", reason="Synthetic"))

    monkeypatch.setattr(AskArgs, "call", call)
    response = post(
        клиент,
        body() | dict(measurement_set_id=saved["id"], measurement_set_revision=saved["revision"]),
    )
    assert response.status_code == 409 and response.get_json()["error"] == "measurement_set_changed"
    assert all(f.level == "D0" for f in get_state(АУДИТОР).findings)
