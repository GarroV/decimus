"""Права MCP читают переключатель экшн-планов один раз на сообщение (#1407).

Вне веба снимка переключателя не было: каждая проверка права шла в базу, а `tools/list`
проверяет права по разу на инструмент.
"""

from __future__ import annotations

import pytest

from src.domain import features
from src.mcp import rpc


def _список() -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


def test_каталог_читает_переключатель_один_раз(monkeypatch: pytest.MonkeyPatch) -> None:
    чтений: list[int] = []

    def читать() -> features.ActionPlanState:
        чтений.append(1)
        return features.ActionPlanState(False)

    monkeypatch.setattr(features, "_load_action_plan_state", читать)

    ответ = rpc.handle(_список(), tenant="HQ", role="admin")

    assert ответ is not None and ответ["result"]["tools"]  # type: ignore[index]
    assert len(чтений) == 1


def test_без_снимка_каждая_проверка_читает_заново(monkeypatch: pytest.MonkeyPatch) -> None:
    """Парная проверка: тест выше красен без `feature_scope`, а не зелен вхолостую."""
    чтений: list[int] = []

    def читать() -> features.ActionPlanState:
        чтений.append(1)
        return features.ActionPlanState(False)

    monkeypatch.setattr(features, "_load_action_plan_state", читать)
    features.action_plans_enabled()
    features.action_plans_enabled()

    assert len(чтений) == 2
