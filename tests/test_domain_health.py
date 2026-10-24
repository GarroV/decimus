"""Цвет подключения на вкладке «Подключения» (D638): правила `src/domain/health.py`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.domain import health
from src.domain.health import GREEN, GREY, RED, YELLOW, LoadFacts, ProbeRow

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
EVERY = timedelta(minutes=15)
FRESH = timedelta(hours=26)


def test_probe_never_checked_is_grey() -> None:
    assert health.of_probe(None, NOW, every=EVERY).light == GREY


def test_probe_fresh_keeps_its_light_and_reason() -> None:
    row = ProbeRow(light=RED, reason="health.reason.rejected", checked_at=NOW - EVERY)
    status = health.of_probe(row, NOW, every=EVERY)
    assert (status.light, status.reason, status.checked_at) == (RED, row.reason, row.checked_at)


def test_probe_stale_turns_yellow_even_if_it_was_green() -> None:
    # Проверка не шла три срока подряд — значит, встал тот, кто проверяет;
    # зелёный последнего захода ничего не говорит о сейчас.
    row = ProbeRow(
        light=GREEN, reason="health.reason.ok", checked_at=NOW - 3 * EVERY - timedelta(seconds=1)
    )
    status = health.of_probe(row, NOW, every=EVERY)
    assert (status.light, status.reason) == (YELLOW, "health.reason.stale")


def test_loads_never_ran_is_grey() -> None:
    assert health.of_loads(None, NOW, fresh_for=FRESH).light == GREY


def test_loads_last_failed_is_red_with_error() -> None:
    facts = LoadFacts(at=NOW - timedelta(hours=1), ok=False, error="401")
    status = health.of_loads(facts, NOW, fresh_for=FRESH)
    assert (status.light, status.reason, status.params["error"]) == (
        RED,
        "health.reason.failed",
        "401",
    )


def test_loads_recent_success_is_green() -> None:
    facts = LoadFacts(at=NOW - timedelta(hours=3), ok=True, error=None)
    assert health.of_loads(facts, NOW, fresh_for=FRESH).light == GREEN


def test_loads_late_is_yellow_then_red() -> None:
    late = LoadFacts(at=NOW - FRESH - timedelta(hours=1), ok=True, error=None)
    stopped = LoadFacts(at=NOW - 2 * FRESH - timedelta(hours=1), ok=True, error=None)
    assert health.of_loads(late, NOW, fresh_for=FRESH).light == YELLOW
    assert health.of_loads(stopped, NOW, fresh_for=FRESH).light == RED


def test_summary_is_the_worst_light_and_ignores_grey() -> None:
    lights = [GREEN, GREY, YELLOW, GREEN]
    assert health.summary(lights) == YELLOW
    assert health.summary([GREEN, RED, YELLOW]) == RED
    assert health.summary([GREY, GREY]) == GREY
    assert health.summary([GREEN, GREY]) == GREEN
