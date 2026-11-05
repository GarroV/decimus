"""D710: журнал шагов обхода — что пишется на каждом шаге и что запись не ломает шаг.

Повод — проверка 05.11.2026: на шаге класса система ответила «нарушение не установлено»,
«Сохранить» осталась неактивной, а в журнале контейнера не осталось ничего. Ядро здесь —
что в строку попадает (слова, число кадров, пункт, класс, вердикт и причина, путь, сбой),
и что упавшая запись журнала не отменяет и не искажает ответ аудитору.
"""

from __future__ import annotations

# Imported pytest fixtures intentionally share their names with fixture parameters.
# ruff: noqa: F811
import pytest
from test_walk_level import body, model, post  # noqa: F401
from test_web_walk import АУДИТОР
from test_web_walk_suggest import Модель, модель  # noqa: F401
from test_web_walk_write import JPEG, Клиент, клиент  # noqa: F401

from src.bot import propose as ядро
from src.db import walk_log
from src.db.walk_log import WalkStep
from src.domain import get_state
from src.recognize.errors import ModelUnavailable
from src.web import walk_suggest
from src.web.walk_steps import CLASS_STATUS_MANUAL, VIA_FALLBACK


def _suggest(клиент: Клиент, **extra: object):
    return клиент.c.post(
        walk_suggest.SUGGEST_PATH,
        json={"words": "повреждённая мусорка на улице", "photos": [клиент.ссылка()]} | extra,
        headers={"X-Telegram-Init-Data": клиент.init},
    )


def _only(steps: list[object]) -> WalkStep:
    assert len(steps) == 1, steps
    step = steps[0]
    assert isinstance(step, WalkStep)
    return step


def test_class_ready_step_carries_input_answer_and_run(
    клиент: Клиент, model, walk_log_steps: list[object]
) -> None:
    reply = post(клиент, body())

    assert reply.status_code == 200
    step = _only(walk_log_steps)
    state = get_state(АУДИТОР)
    assert (step.step, step.outcome, step.verdict, step.level) == ("class", "ok", "ready", "D1")
    assert (step.item_code, step.zone, step.photos) == ("CLN05", "hot_kitchen", 0)
    assert step.words == "Auditor confirmed synthetic facts"
    assert step.reason == "Synthetic criterion met"
    assert (step.chat_id, step.run_id, step.unit) == (АУДИТОР, state.run_id, state.unit)
    assert step.visit_date == state.visit_date() and step.duration_ms is not None


def test_not_established_verdict_and_reason_are_recorded(
    клиент: Клиент, model, walk_log_steps: list[object]
) -> None:
    _, payload = model
    payload.update(level=None, need_fact="", reason="Facts do not establish a violation")

    assert post(клиент, body()).status_code == 200

    step = _only(walk_log_steps)
    assert step.verdict == "not_established" and step.level is None
    assert step.reason == "Facts do not establish a violation"


def test_clarified_facts_are_their_own_step(
    клиент: Клиент, model, walk_log_steps: list[object]
) -> None:
    chain = [{"question": "Was production stopped?", "answer": "yes"}]

    assert post(клиент, body() | {"clarifications": chain}).status_code == 200

    step = _only(walk_log_steps)
    assert step.step == "class_facts" and step.detail["clarifications"] == 1


def test_refused_class_step_names_the_refusal(
    клиент: Клиент, model, walk_log_steps: list[object]
) -> None:
    assert post(клиент, body() | {"words": "", "photos": []}).status_code == 422

    step = _only(walk_log_steps)
    assert step.outcome == "refused" and step.error == "missing_facts"
    assert step.detail["reason_code"] == "walk.level.missing_facts"


def test_suggest_records_offered_items_and_path(
    клиент: Клиент, модель: Модель, walk_log_steps: list[object]
) -> None:
    assert _suggest(клиент).status_code == 200

    step = _only(walk_log_steps)
    assert (step.step, step.outcome, step.via, step.item_code) == (
        "suggest",
        "ok",
        "model",
        "CLN05",
    )
    assert step.photos == 1 and step.words == "повреждённая мусорка на улице"
    assert step.detail["candidates"][0]["code"] == "CLN05"


def test_suggest_with_model_down_is_recorded_as_fallback(
    клиент: Клиент, модель: Модель, monkeypatch: pytest.MonkeyPatch, walk_log_steps: list[object]
) -> None:
    def down(*a: object, **k: object) -> None:
        raise ModelUnavailable("secret-key-in-message")

    monkeypatch.setattr(ядро, "classify", down)

    assert _suggest(клиент).status_code == 503

    step = _only(walk_log_steps)
    assert (step.outcome, step.via, step.error) == ("error", VIA_FALLBACK, "ModelUnavailable")
    assert "secret-key" not in repr(step), "текст исключения в журнал не идёт"


def test_save_records_text_class_and_how_it_was_chosen(
    клиент: Клиент, walk_log_steps: list[object]
) -> None:
    ref = клиент.ссылка()
    reply = клиент.запись(
        op="add",
        zone="hot_kitchen",
        code="CLN05",
        level="D1",
        text="Нагар на поду",
        photos=[ref],
        class_status=CLASS_STATUS_MANUAL,
        words="нагар",
        run_id=get_state(АУДИТОР).run_id,
    )

    assert reply.status_code == 200, reply.get_json()
    manual, save = [s for s in walk_log_steps if isinstance(s, WalkStep)]
    assert manual.step == "class_manual" and manual.level == "D1"
    assert (save.step, save.outcome, save.verdict) == ("save", "ok", CLASS_STATUS_MANUAL)
    assert save.detail["text"] == "Нагар на поду" and save.photos == 1


def test_remove_and_refused_write_are_recorded(
    клиент: Клиент, walk_log_steps: list[object]
) -> None:
    run_id = get_state(АУДИТОР).run_id
    bad = клиент.запись(
        op="add", zone="hot_kitchen", code="CLN05", level="D1", text="", run_id=run_id
    )
    assert bad.status_code == 422

    refused = [s for s in walk_log_steps if isinstance(s, WalkStep)][-1]
    assert (refused.step, refused.outcome) == ("save", "refused")

    walk_log_steps.clear()
    клиент.запись(op="drop", n=1, run_id=run_id)
    assert _only(walk_log_steps).step == "remove"


def test_a_failing_journal_never_changes_the_auditors_answer(
    клиент: Клиент, model, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(step: WalkStep) -> None:
        raise RuntimeError("журнал недоступен")

    monkeypatch.setattr("src.db.walk_log.submit", broken)

    reply = post(клиент, body())

    assert reply.status_code == 200 and reply.get_json()["status"] == "ready"


# ── сама запись ────────────────────────────────────────────────────────

_REAL_SUBMIT = walk_log.submit


def test_record_swallows_a_database_failure_and_logs_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from src.db.errors import AccessError

    def down(_: str):
        raise AccessError("База недоступна")

    monkeypatch.setattr(walk_log, "_connected", down)

    walk_log.record(WalkStep(chat_id=1, step="class", outcome="ok"))

    assert "журнал обхода: запись не прошла" in caplog.text


def test_submit_never_raises_and_drops_when_queue_is_full(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(walk_log._state, "pending", walk_log.MAX_PENDING)

    _REAL_SUBMIT(WalkStep(chat_id=1, step="class", outcome="ok"))

    assert "очередь полна" in caplog.text
