"""F-108: сборки отчёта идут не больше `MAX_CONCURRENT_BUILDS` разом, лишние ждут или отказывают."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from src.report import engine
from src.report.errors import ReportError


def _launch_once() -> None:
    engine._launch(["x"], work=Path("."), env={}, settings=None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _свежие_места(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "report_script", lambda _settings: Path("report.py"))
    monkeypatch.setattr(
        engine, "_build_slots", threading.BoundedSemaphore(engine.MAX_CONCURRENT_BUILDS)
    )


def test_concurrent_builds_never_exceed_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    running = 0
    peak = 0
    guard = threading.Lock()

    def fake_run(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        nonlocal running, peak
        with guard:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with guard:
            running -= 1
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    threads = [
        threading.Thread(target=_launch_once) for _ in range(engine.MAX_CONCURRENT_BUILDS * 3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == engine.MAX_CONCURRENT_BUILDS  # все места использованы, больше — нет


def test_over_cap_waits_then_refuses_with_busy_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    for _ in range(engine.MAX_CONCURRENT_BUILDS):
        engine._build_slots.acquire()
    monkeypatch.setattr(engine, "QUEUE_WAIT_SEC", 0.05)
    with pytest.raises(ReportError, match="занята"):
        _launch_once()


def test_slot_is_released_after_timeout_or_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise subprocess.TimeoutExpired("x", 1)

    monkeypatch.setattr(engine.subprocess, "run", boom)
    for _ in range(engine.MAX_CONCURRENT_BUILDS + 2):
        with pytest.raises(ReportError, match="не закончилась"):
            _launch_once()
