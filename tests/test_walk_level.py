"""Selected criterion checks are authenticated reads; all model calls are synthetic."""

from __future__ import annotations

# Imported pytest fixtures intentionally share their names with fixture parameters.
# ruff: noqa: F811
from types import SimpleNamespace

import pytest
from test_selected_level import CFG, method
from test_web_walk import АУДИТОР
from test_web_walk_write import JPEG, Клиент, клиент  # noqa: F401

from src.domain import get_state, start_inspection
from src.domain.model_usage import current_scope
from src.recognize.classify import AskArgs
from src.recognize.client import ModelAnswer
from src.web import walk_level


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):
    from src.recognize import selected_level

    calls = []
    payload = {"level": "D1", "need_fact": "", "reason": "Synthetic criterion met"}

    def call(ask):
        calls.append((ask, current_scope()))
        return ModelAnswer(dict(payload))

    monkeypatch.setattr(AskArgs, "call", call)
    monkeypatch.setattr(selected_level, "load_recognize_settings", lambda: CFG)
    monkeypatch.setattr(
        walk_level, "try_hold", lambda *a, **k: SimpleNamespace(acquired=True, release=lambda: None)
    )
    return calls, payload


def body():
    return {
        "run_id": get_state(АУДИТОР).run_id,
        "selection_revision": "selection-1",
        "code": "CLN05",
        "zone": "hot_kitchen",
        "words": "Auditor confirmed synthetic facts",
        "photos": [],
    }


def post(client, data):
    return client.c.post(
        walk_level.LEVEL_PATH, json=data, headers={"X-Telegram-Init-Data": client.init}
    )


def test_ready_result_is_bound_and_usage_scoped_without_writing(клиент: Клиент, model) -> None:
    before = get_state(АУДИТОР)
    reply = post(клиент, body())
    assert reply.status_code == 200, reply.get_json()
    got = reply.get_json()
    assert got["status"] == "ready" and got["level"] == "D1" and got["provisional_level"] is None
    assert got["code"] == "CLN05" and got["selection_revision"] == "selection-1"
    assert got["run_id"] == before.run_id
    calls, _ = model
    assert len(calls) == 1
    scope = calls[0][1]
    assert (
        scope.telegram_id == АУДИТОР
        and scope.inspection_ref == before.run_id
        and scope.kind == "suggest"
    )
    assert get_state(АУДИТОР) == before


def test_need_fact_has_no_ready_class_and_only_assigned_own_frames_are_sent(
    клиент: Клиент,
    model,
) -> None:
    ref = клиент.ссылка()
    calls, payload = model
    payload["need_fact"] = "Which missing synthetic fact?"
    reply = post(клиент, body() | {"photos": [ref, ref]})
    assert reply.status_code == 200
    got = reply.get_json()
    assert (
        got["level"] is None and got["provisional_level"] == "D1" and got["status"] == "needs_fact"
    )
    assert got["photo_refs"] == [ref] and got["facts_from"]["photos"] == 1
    assert calls[0][0].photos == (JPEG,)


@pytest.mark.parametrize(
    "change,error",
    [
        ({"words": "", "photos": []}, "missing_facts"),
        ({"code": "UNKNOWN"}, "invalid_selection"),
        ({"reading_c": 0, "reading_source": "model"}, "reading_unconfirmed"),
        ({"photos": ["walk:" + "0" * 32]}, "invalid_request"),
        ({"selection_revision": "x" * 129}, "invalid_selection"),
    ],
)
def test_bad_or_missing_facts_do_not_call_model(клиент: Клиент, model, change, error) -> None:
    before = get_state(АУДИТОР)
    reply = post(клиент, body() | change)
    assert reply.status_code == 422
    assert reply.get_json()["error"] == error and reply.get_json()["level"] is None
    assert model[0] == [] and get_state(АУДИТОР) == before


def test_missing_and_malformed_need_fact_are_not_success(клиент: Клиент, model) -> None:
    _, payload = model
    payload.pop("need_fact")
    reply = post(клиент, body())
    assert reply.status_code == 503 and reply.get_json()["level"] is None


def test_explicit_human_confirmation_can_confirm_model_origin_zero(клиент: Клиент, model) -> None:
    reply = post(
        клиент, body() | {"reading_c": 0, "reading_confirmed": True, "reading_source": "model"}
    )
    assert reply.status_code == 200
    assert reply.get_json()["facts_from"]["confirmed_reading"] is True
    assert "0 °C" in model[0][0][0].question


def test_stale_run_before_or_after_call_never_returns_current_level(
    клиент: Клиент,
    model,
    monkeypatch,
) -> None:
    request = body()
    start_inspection(АУДИТОР, unit="replacement", kind="planned", report_lang="ru")
    assert post(клиент, request).status_code == 409
    assert model[0] == []

    def replace_during_call(ask):
        start_inspection(АУДИТОР, unit="replacement again", kind="planned", report_lang="ru")
        return ModelAnswer({"level": "D1", "need_fact": "", "reason": "old run"})

    monkeypatch.setattr(AskArgs, "call", replace_during_call)
    reply = post(клиент, body())
    assert reply.status_code == 409 and reply.get_json()["error"] == "run_changed"
    assert reply.get_json()["level"] is None


def test_missing_criterion_is_explicit_and_no_model_call(
    клиент: Клиент,
    model,
    tmp_path,
    monkeypatch,
) -> None:
    method(tmp_path, monkeypatch, "## CLN06\nSynthetic other criterion\n")
    start_inspection(АУДИТОР, unit="no criteria", kind="planned", report_lang="ru")
    reply = post(клиент, body())
    assert reply.status_code == 422 and reply.get_json()["error"] == "criteria_unavailable"
    assert model[0] == []


def test_level_auth_and_foreign_photo_cannot_reach_model(клиент: Клиент, model) -> None:
    unsigned = клиент.c.post(walk_level.LEVEL_PATH, json=body())
    assert unsigned.status_code in (401, 403)
    other = 777
    start_inspection(other, unit="other actor", kind="planned", report_lang="ru")
    other_client = Клиент(клиент.c, user_id=other)
    ref = other_client.ссылка()
    reply = post(клиент, body() | {"photos": [ref]})
    assert reply.status_code == 422 and model[0] == []


def test_level_bounded_inputs_and_requested_edition_no_model(клиент: Клиент, model) -> None:
    for change, status in [
        ({"words": "x" * 1001}, 422),
        ({"photos": ["x"] * 11}, 422),
        ({"checklist_version": "stale edition"}, 409),
        ({"words": "x" * (walk_level.MAX_LEVEL_BODY_BYTES + 1)}, 413),
    ]:
        reply = post(клиент, body() | change)
        assert reply.status_code == status
        assert reply.get_json()["level"] is None
    assert model[0] == []


def test_sealed_or_busy_level_has_no_model_call(клиент: Клиент, model, monkeypatch) -> None:
    from src.bot import sidecar

    monkeypatch.setattr(walk_level, "try_hold", lambda *a, **k: SimpleNamespace(acquired=False))
    assert post(клиент, body()).status_code == 429
    assert model[0] == []
    sidecar.mark_handed_over(АУДИТОР, 0)
    assert post(клиент, body()).status_code == 409
    assert model[0] == []


def test_rebound_edition_after_model_discards_result(клиент: Клиент, model, monkeypatch) -> None:
    from src.domain import check_environment
    from src.domain.engine import state_file
    from src.domain.state import patch_domain_block

    def rebound(ask):
        patch_domain_block(
            state_file(АУДИТОР, check_environment()), {"checklist_version": "new synthetic edition"}
        )
        return ModelAnswer({"level": "D1", "need_fact": "", "reason": "old edition"})

    monkeypatch.setattr(AskArgs, "call", rebound)
    reply = post(клиент, body())
    assert reply.status_code == 409 and reply.get_json()["error"] == "context_changed"
    assert reply.get_json()["level"] is None


def test_level_timing_contains_only_status_and_numerical_stage_data(
    клиент: Клиент, model, caplog
) -> None:
    import logging

    words = "private synthetic fact do not log"
    with caplog.at_level(logging.INFO, logger=walk_level.__name__):
        assert post(клиент, body() | {"words": words}).status_code == 200
    log = "\n".join(
        record.message for record in caplog.records if record.name == walk_level.__name__
    )
    assert "status=200" in log and "level_prepare" in log and "level_recheck" in log
    assert words not in log


def test_level_proxy_preserves_auth_and_no_store_response(
    клиент: Клиент, model, monkeypatch
) -> None:
    from contextlib import contextmanager
    from urllib.parse import urlsplit

    from flask import Flask

    from src.web import walk_proxy

    @contextmanager
    def service(outgoing, **_kwargs):
        reply = клиент.c.post(
            urlsplit(outgoing.full_url).path,
            data=outgoing.data,
            headers=dict(outgoing.header_items()),
        )
        yield SimpleNamespace(status=reply.status_code, read=reply.get_data, headers=reply.headers)

    monkeypatch.setattr(walk_proxy._OPENER, "open", service)
    proxy = Flask(__name__)
    walk_proxy.install(proxy, upstream="http://walk.invalid", ui_lang="ru")
    client = proxy.test_client()
    assert client.post(walk_level.LEVEL_PATH, json=body()).status_code in (401, 403)
    assert model[0] == []
    reply = client.post(
        walk_level.LEVEL_PATH, json=body(), headers={"X-Telegram-Init-Data": клиент.init}
    )
    assert reply.status_code == 200 and reply.get_json()["status"] == "ready"
    assert reply.headers["Cache-Control"] == "no-store"
    assert len(model[0]) == 1


def test_search_and_selected_level_share_auditor_model_session(
    клиент: Клиент, model, monkeypatch
) -> None:
    from src.bot.propose import Offer
    from src.recognize.models import Candidate
    from src.web import walk_suggest

    nested = []
    monkeypatch.setattr(
        walk_suggest,
        "try_hold",
        lambda *a, **k: SimpleNamespace(acquired=True, release=lambda: None),
    )

    def search(*args, **kwargs):
        nested.append(post(клиент, body()).status_code)
        return Offer(
            via="model",
            candidates=(
                Candidate(
                    code="CLN05", level="D1", zone="hot_kitchen", wording="Synthetic", confidence=1
                ),
            ),
        )

    monkeypatch.setattr(walk_suggest, "propose", search)
    ref = клиент.ссылка()
    reply = клиент.c.post(
        walk_suggest.SUGGEST_PATH,
        json={"words": "Synthetic", "photos": [ref]},
        headers={"X-Telegram-Init-Data": клиент.init},
    )
    assert reply.status_code == 200
    assert nested == [429] and model[0] == []
    assert post(клиент, body()).status_code == 200


def test_level_releases_budget_after_failure_and_total_photo_bytes_are_bounded(
    клиент: Клиент, model, monkeypatch
) -> None:
    _, payload = model
    payload["need_fact"] = None
    assert post(клиент, body()).status_code == 503
    payload["need_fact"] = ""
    assert post(клиент, body()).status_code == 200
    ref = клиент.ссылка()
    before = len(model[0])
    monkeypatch.setattr(walk_level, "MAX_LEVEL_IMAGE_BYTES", 1)
    assert post(клиент, body() | {"photos": [ref]}).status_code == 422
    assert len(model[0]) == before


def test_unknown_active_edition_is_not_replaced_with_current_catalogue(
    клиент: Клиент, model
) -> None:
    from src.domain import check_environment
    from src.domain.engine import state_file
    from src.domain.state import patch_domain_block

    patch_domain_block(state_file(АУДИТОР, check_environment()), {"checklist_version": ""})
    reply = post(клиент, body())
    assert reply.status_code == 422 and reply.get_json()["error"] == "criteria_unavailable"
    assert model[0] == []


def test_search_and_level_share_total_slots_across_auditors(
    клиент: Клиент, model, monkeypatch
) -> None:
    from test_web_walk import ТОКЕН, _приложение

    from src.bot.propose import Offer
    from src.recognize.models import Candidate
    from src.web import walk, walk_suggest
    from src.web.server_limits import SlowGate
    from src.web.walk_model_session import ModelSession

    session = ModelSession()
    session.gate = SlowGate(1)
    monkeypatch.setattr(walk, "ModelSession", lambda: session)
    client = Клиент(_приложение(monkeypatch, TELEGRAM_BOT_TOKEN=ТОКЕН).test_client())
    start_inspection(777, unit="other actor", kind="planned", report_lang="ru")
    other = Клиент(client.c, user_id=777)
    ref = other.ссылка()
    monkeypatch.setattr(
        walk_suggest,
        "try_hold",
        lambda *a, **k: SimpleNamespace(acquired=True, release=lambda: None),
    )
    nested = []

    def ask(_ask_args):
        reply = other.c.post(
            walk_suggest.SUGGEST_PATH,
            json={"words": "Synthetic", "photos": [ref]},
            headers={"X-Telegram-Init-Data": other.init},
        )
        nested.append(reply.status_code)
        return ModelAnswer({"level": "D1", "need_fact": "", "reason": "Synthetic criterion"})

    monkeypatch.setattr(AskArgs, "call", ask)
    monkeypatch.setattr(
        walk_suggest,
        "propose",
        lambda *a, **k: Offer(
            via="model",
            candidates=(
                Candidate(
                    code="CLN05", level="D1", zone="hot_kitchen", wording="Synthetic", confidence=1
                ),
            ),
        ),
    )
    assert post(client, body()).status_code == 200
    assert nested == [503]
    assert (
        other.c.post(
            walk_suggest.SUGGEST_PATH,
            json={"words": "Synthetic", "photos": [ref]},
            headers={"X-Telegram-Init-Data": other.init},
        ).status_code
        == 200
    )


@pytest.mark.parametrize("question,status", [("", "not_established"), ("How many?", "needs_fact")])
def test_null_violation_and_clarification_echo(клиент: Клиент, model, question, status):
    calls, payload = model
    payload.update(
        level=None, need_fact=question, reason="Synthetic facts do not establish a violation"
    )
    chain = [{"question": "Was production stopped?", "answer": "yes"}]
    reply = post(клиент, body() | {"clarifications": chain})
    assert reply.status_code == 200
    got = reply.get_json()
    assert got["status"] == status and got["level"] is None
    assert got["clarifications"] == chain and len(got["clarification_hash"]) == 64
    assert "yes" in calls[0][0].question
    assert get_state(АУДИТОР).findings == []


@pytest.mark.parametrize(
    "change",
    [
        {"level": None, "need_fact": None},
        {"level": "D0"},
        {"level": None, "reason": ""},
        {"unexpected": True},
    ],
)
def test_selected_malformed_null_is_error_not_no_violation(клиент: Клиент, model, change):
    _, payload = model
    payload.update(change)
    reply = post(клиент, body())
    assert reply.status_code == 503 and reply.get_json()["status"] == "unavailable"


def test_confirmed_add_saves_bound_chain_and_human_words_together(клиент: Клиент):
    ref = клиент.ссылка()
    state = get_state(АУДИТОР)
    chain = [{"question": "Was production stopped?", "answer": "yes"}]
    context = {
        "run_id": state.run_id,
        "checklist_version": state.checklist_version,
        "code": "CLN05",
        "zone": "hot_kitchen",
        "photo_refs": [ref],
        "clarifications": chain,
    }
    body = dict(
        op="add",
        code="CLN05",
        zone="hot_kitchen",
        level="D1",
        text="Human description",
        photos=[ref],
        words="Original observation\nyes",
        class_context=context,
        run_id=state.run_id,
    )
    result = клиент.запись(**body)
    assert result.status_code == 200, result.get_json()
    saved = get_state(АУДИТОР)
    assert saved.findings[0].words == body["words"]
    assert saved.finding_history[0]["clarifications"] == chain
    assert saved.finding_history[0]["after"][0]["n"] == saved.findings[0].n


@pytest.mark.parametrize("context_value", [None, {}, {"clarifications": []}])
def test_invalid_add_context_does_not_create_finding(клиент: Клиент, context_value):
    ref = клиент.ссылка()
    result = клиент.запись(
        op="add",
        code="CLN05",
        zone="hot_kitchen",
        level="D1",
        text="Human description",
        photos=[ref],
        class_context=context_value,
    )
    assert result.status_code in (400, 422)
    assert get_state(АУДИТОР).findings == []
