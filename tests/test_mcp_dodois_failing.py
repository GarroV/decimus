"""dodois_status называет виды, которые не грузятся, даже при живом входе (#1709)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.db import dodois_logins, dodois_metrics
from src.mcp import dodois_read

СЕЙЧАС = datetime(2026, 11, 14, 10, tzinfo=UTC)


def _load(country: str, kind: str, ok: bool) -> dodois_metrics.KindLoad:
    return dodois_metrics.KindLoad(
        country,
        kind,
        СЕЙЧАС if ok else None,
        1 if ok else None,
        СЕЙЧАС,
        ok,
        None if ok else "unauthorized",
    )


def test_failing_kinds_named_per_country_and_on_top(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dodois_logins, "list_logins", lambda: [])
    monkeypatch.setattr(dodois_logins, "list_invites", lambda limit: [])
    monkeypatch.setattr(dodois_metrics, "country_data", lambda month: [])
    monkeypatch.setattr(
        dodois_metrics,
        "kind_loads",
        lambda: [
            _load("BY", "ratings", False),
            _load("BY", "sales", True),
            _load("LT", "ratings", True),
        ],
    )
    answer = dodois_read.dodois_status(tenant="HQ")
    by_country = {row["country"]: row for row in answer["countries"]}
    assert by_country["BY"]["failing_kinds"] == ["ratings"]
    assert by_country["LT"]["failing_kinds"] == []
    assert answer["failing"] == [{"country": "BY", "kinds": ["ratings"]}]
