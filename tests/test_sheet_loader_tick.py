"""F-124: непредвиденный сбой забора таблицы не оставляет заявку открытой.

Раньше `_tick` ловил только `SyncError`: любое другое исключение вылетало до
`finish_request`, заявка оставалась открытой, и бот брал её снова каждую минуту.
Базы не нужно: состояние, сам забор и замок загрузчика (F-125) подменены.
"""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import pytest

from src.bot import sheet_loader


def _заявка(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    закрытые: list[dict[str, Any]] = []
    monkeypatch.setattr(sheet_loader, "job_lock", lambda *_a, **_k: nullcontext(True))
    monkeypatch.setattr(sheet_loader.state, "open_request", lambda: SimpleNamespace(id=7))
    monkeypatch.setattr(
        sheet_loader.state,
        "finish_request",
        lambda request_id, *, ok, error: закрытые.append(
            {"id": request_id, "ok": ok, "error": error}
        ),
    )
    return закрытые


def test_непредвиденный_сбой_закрывает_заявку_неудачей(monkeypatch: pytest.MonkeyPatch) -> None:
    закрытые = _заявка(monkeypatch)

    def _падает() -> None:
        raise ValueError("секретный путь /srv/x")

    monkeypatch.setattr(sheet_loader.sheet_sync, "run", _падает)

    sheet_loader._tick()

    assert закрытые == [{"id": 7, "ok": False, "error": "ValueError"}], (
        "заявка осталась бы открытой и бралась бы каждую минуту; текст исключения в неё не идёт"
    )
