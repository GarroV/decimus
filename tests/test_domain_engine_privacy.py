"""Engine operational diagnostics keep user arguments out of logs and tracebacks."""

from __future__ import annotations

import subprocess
import traceback
from pathlib import Path

import pytest

from src.domain import engine
from src.domain.config import check_environment
from src.domain.errors import EngineError

PRIVATE = "SYNTHETIC_PRIVATE_ARGUMENT"


@pytest.mark.parametrize("operation", ["init", "add", "edit", PRIVATE])
@pytest.mark.parametrize("phase", ["retry", "exhausted", "started"])
def test_runtime_diagnostics_keep_only_the_known_operation(caplog, operation, phase):
    args = [operation, f"--contact={PRIVATE}", "--evidence", PRIVATE]
    output = engine.RUNTIME_BEFORE_SCRIPT if phase != "started" else "fatal after initialization"
    attempt = engine.ENGINE_ATTEMPTS if phase == "exhausted" else 1
    if phase == "retry":
        engine._refuse_no_verdict(args, output=output, attempt=1, chat_id=41)
    else:
        with pytest.raises(EngineError) as caught:
            engine._refuse_no_verdict(args, output=output, attempt=attempt, chat_id=41)
        assert PRIVATE not in str(caught.value)
        assert caught.value.command == (operation if operation != PRIVATE else "audit")
    assert PRIVATE not in caplog.text
    assert (operation if operation != PRIVATE else "audit") in caplog.text


def test_timeout_traceback_never_includes_the_subprocess_arguments(domain_env: Path, monkeypatch):
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=90, stderr=PRIVATE)

    monkeypatch.setattr(engine.subprocess, "run", timeout)
    with pytest.raises(EngineError) as caught:
        engine.run_audit(
            ["add", f"--evidence={PRIVATE}"],
            chat_id=41,
            settings=check_environment(),
            create=True,
        )
    assert PRIVATE not in "".join(traceback.format_exception(caught.value))
    assert caught.value.command == "add"


def test_real_engine_refusal_text_is_preserved_while_command_metadata_is_safe(
    domain_env: Path, monkeypatch
):
    monkeypatch.setattr(
        engine,
        "_launch",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 2, "", "Отклонено движком"),
    )
    with pytest.raises(EngineError) as caught:
        engine.run_audit(
            ["add", f"--evidence={PRIVATE}"],
            chat_id=41,
            settings=check_environment(),
            create=True,
        )
    assert caught.value.message == "Отклонено движком"
    assert caught.value.command == "add"
