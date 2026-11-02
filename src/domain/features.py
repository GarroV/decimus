"""Operational feature switches; a paused workflow preserves its stored history."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime

from src.settings_read import BooleanSetting, SettingsUnavailable, read_boolean


@dataclass(frozen=True)
class ActionPlanState:
    enabled: bool
    known: bool = True
    saved: BooleanSetting | None = None

    @property
    def notifications_after(self) -> datetime | None:
        return None if self.saved is None else self.saved.notifications_after


_SCOPE: ContextVar[list[ActionPlanState] | None] = ContextVar("feature_snapshot", default=None)


def begin_feature_scope() -> Token[list[ActionPlanState] | None]:
    """One lazy snapshot for one request/operation, including failed reads."""
    return _SCOPE.set([])


def end_feature_scope(token: Token[list[ActionPlanState] | None]) -> None:
    _SCOPE.reset(token)


@contextmanager
def feature_scope() -> Iterator[None]:
    token = begin_feature_scope()
    try:
        yield
    finally:
        end_feature_scope(token)


def _load_action_plan_state() -> ActionPlanState:
    """Persisted choice wins over env; failed DB reads fail closed, without cache."""
    try:
        saved = read_boolean("action_plans_enabled")
    except SettingsUnavailable:
        return ActionPlanState(False, known=False)
    if saved is not None:
        return ActionPlanState(saved.enabled, saved=saved)
    fallback = os.environ.get("ACTION_PLANS_ENABLED", "0").strip().lower()
    return ActionPlanState(fallback in {"1", "true", "yes"})


def action_plan_state() -> ActionPlanState:
    """Fresh outside an operation; stable inside it, never cached across requests."""
    scope = _SCOPE.get()
    if scope:
        return scope[0]
    state = _load_action_plan_state()
    if scope is not None:
        scope.append(state)
    return state


def action_plans_enabled() -> bool:
    """Electronic action plans are paused by default by the owner's decision."""
    return action_plan_state().enabled
