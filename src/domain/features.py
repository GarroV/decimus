"""Operational feature switches; a paused workflow preserves its stored history."""

from __future__ import annotations

import os


def action_plans_enabled() -> bool:
    """Electronic action plans are paused by default by the owner's decision."""
    return os.environ.get("ACTION_PLANS_ENABLED", "0").strip().lower() in {"1", "true", "yes"}
