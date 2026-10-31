"""Actual Flask writes log only numeric request-local durations, even on refusal."""

from __future__ import annotations

import logging

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import JPEG, Клиент, клиент  # noqa: F401

from src.recognize.timing import collect, measure, report
from src.web import walk_write
from src.web.walk_write_timing import logger

# Imported pytest fixture intentionally shares its name with test parameters.
# ruff: noqa: F811


def records(caplog):
    return [record for record in caplog.records if record.name == logger.name]


def assert_numeric(record, operation, status):
    assert record.msg == "Обход: время записи operation=%s status=%s timing=%s"
    op, actual_status, timing = record.args
    assert op == operation and actual_status == status
    assert isinstance(timing["ms"], int) and timing["ms"] >= 0
    assert timing["model_ms"] == 0
    assert set(timing) == {"ms", "model_ms", "timings_ms"}
    assert set(timing["timings_ms"]) <= {"lookup", "mutation", "render"}
    assert all(isinstance(value, int) and value >= 0 for value in timing["timings_ms"].values())
    assert str(АУДИТОР) not in record.getMessage()
    assert "PRIVATE_WORDS" not in record.getMessage() and "walk:" not in record.getMessage()
    return timing


def test_success_photo_finding_info_numeric_stages_and_context_reset(клиент: Клиент, caplog):
    caplog.set_level(logging.INFO, logger=logger.name)
    photo = клиент.кадр(JPEG)
    assert photo.status_code == 201
    ref = photo.get_json()["ref"]
    finding = клиент.запись(
        op="add",
        code="CLN05",
        level="D1",
        zone="hot_kitchen",
        text="PRIVATE_WORDS",
        words="PRIVATE_WORDS",
        photos=[ref],
    )
    assert finding.status_code == 200
    info = клиент.сведение(code="INF08", value="PRIVATE_WORDS")
    assert info.status_code == 200
    logged = records(caplog)
    assert len(logged) == 3
    for record, op, status in zip(logged, [3, 1, 2], [201, 200, 200], strict=True):
        timing = assert_numeric(record, op, status)
        assert set(timing["timings_ms"]) == {"lookup", "mutation", "render"}
    assert report() == {"ms": 0, "model_ms": 0, "timings_ms": {}}


@pytest.mark.parametrize(
    "operation,path",
    [(1, walk_write.FINDING_PATH), (2, walk_write.INFO_PATH), (3, walk_write.PHOTO_PATH)],
)
def test_auth_failure_is_timed_without_body_or_identity(клиент: Клиент, caplog, operation, path):
    caplog.set_level(logging.INFO, logger=logger.name)
    reply = клиент.c.post(path, json={"words": "PRIVATE_WORDS"})
    assert reply.status_code == 401
    assert len(records(caplog)) == 1
    assert_numeric(records(caplog)[0], operation, 401)
    assert report()["timings_ms"] == {}


@pytest.mark.parametrize(
    "body,status",
    [
        (None, 400),
        ({"op": "unknown"}, 422),
        (
            {
                "op": "add",
                "code": "NO_SUCH_CODE",
                "zone": "hot_kitchen",
                "level": "D1",
                "text": "PRIVATE_WORDS",
                "photos": [],
            },
            422,
        ),
    ],
)
def test_validation_and_domain_rejection_have_real_status(клиент: Клиент, caplog, body, status):
    caplog.set_level(logging.INFO, logger=logger.name)
    reply = клиент.c.post(
        walk_write.FINDING_PATH, json=body, headers={"X-Telegram-Init-Data": клиент.init}
    )
    assert reply.status_code == status
    assert_numeric(records(caplog)[0], 1, status)


def test_raised_photo_http413_is_timed_and_outer_context_restored(клиент: Клиент, caplog):
    caplog.set_level(logging.INFO, logger=logger.name)
    with collect() as outer:
        with measure("outer"):
            reply = клиент.кадр(b"x" * (walk_write.MAX_UPLOAD_BYTES + 1))
        assert reply.status_code == 413
        assert set(outer.stages_ns) == {"outer"}
    assert_numeric(records(caplog)[0], 3, 413)
    assert report()["timings_ms"] == {}


def test_unexpected_exception_logs500_and_does_not_leak_context(
    клиент: Клиент, caplog, monkeypatch
):
    caplog.set_level(logging.INFO, logger=logger.name)

    def fail(*args):
        raise RuntimeError("PRIVATE_WORDS")

    monkeypatch.setattr(walk_write, "_finding_op", fail)
    клиент.c.application.config["PROPAGATE_EXCEPTIONS"] = True
    with pytest.raises(RuntimeError):
        клиент.запись(op="add")
    assert_numeric(records(caplog)[0], 1, 500)
    assert report()["timings_ms"] == {}


def test_engine_rejection_keeps_422_timing_and_does_not_render_success(клиент: Клиент, caplog):
    ref = клиент.ссылка()
    body = dict(
        op="add", code="CLN05", level="D1", zone="hot_kitchen", text="PRIVATE_WORDS", photos=[ref]
    )
    assert клиент.запись(**body).status_code == 200
    caplog.clear()
    caplog.set_level(logging.INFO, logger=logger.name)
    reply = клиент.запись(**body)
    assert reply.status_code == 422
    timing = assert_numeric(records(caplog)[0], 1, 422)
    assert "mutation" in timing["timings_ms"] and "render" not in timing["timings_ms"]
