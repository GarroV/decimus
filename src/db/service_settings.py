"""Manual service settings; no backlog processing or notifications on toggle."""

from __future__ import annotations

import psycopg

from .config import load_retraction_settings
from .errors import DbError

_SAVE_SQL = """
insert into service_settings (key, enabled, notifications_after, changed_by)
values ('action_plans_enabled', %s, clock_timestamp(), %s)
on conflict (key) do update
set enabled = excluded.enabled,
    notifications_after = case
        when excluded.enabled and not service_settings.enabled
        then clock_timestamp() else service_settings.notifications_after end,
    changed_by = excluded.changed_by, changed_at = clock_timestamp()
"""


def set_action_plans(enabled: bool, *, actor: str) -> None:
    """Persist the explicit choice, even when it equals the env fallback.

    The activation watermark hides old unread notifications on first enable
    and every OFF→ON transition. Repeated ON saves do not hide new events.
    """
    if type(enabled) is not bool or not actor.strip():
        raise ValueError("A boolean choice and actor are required")
    try:
        with psycopg.connect(load_retraction_settings().dsn, connect_timeout=3) as conn:
            conn.execute("set local statement_timeout = '3000ms'")
            conn.execute(_SAVE_SQL, (enabled, actor.strip()))
    except psycopg.Error as exc:
        raise DbError(f"Service setting not saved ({type(exc).__name__})") from exc
