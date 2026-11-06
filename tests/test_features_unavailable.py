"""#1407: недоступная настройка экшн-планов — выключено, но с записью в журнале."""

from __future__ import annotations

import logging

import pytest

from src.domain import features
from src.settings_read import SettingsUnavailable


def test_сбой_чтения_настройки_планы_выключены_и_сказано_в_журнале(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def недоступна(_name: str) -> None:
        raise SettingsUnavailable("OperationalError")

    monkeypatch.setattr(features, "read_boolean", недоступна)

    with caplog.at_level(logging.WARNING, logger="src.domain.features"):
        state = features.action_plan_state()

    assert (state.enabled, state.known) == (False, False)
    assert any("экшн-планов не прочитан" in r.getMessage() for r in caplog.records), (
        "сбой чтения настройки прошёл без строки в журнале"
    )
