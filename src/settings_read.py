"""Read-only infrastructure adapter below domain; no product-layer imports.

DATABASE_URL is the shared application connection, as in db.config. Writes
and privileged connection validation remain in db.service_settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import psycopg


class SettingsUnavailable(Exception):
    """No trustworthy persisted setting could be read."""


@dataclass(frozen=True)
class BooleanSetting:
    enabled: bool
    notifications_after: datetime | None
    changed_by: str
    changed_at: datetime


def read_boolean(key: str) -> BooleanSetting | None:
    """Fresh read, bounded connection/query; None means not configured.

    Without a database (standalone domain tools), the environment fallback is
    available. A configured but unavailable database must never enable a feature.
    """
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        return None
    try:
        with psycopg.connect(
            dsn, connect_timeout=3, options="-c statement_timeout=1000", autocommit=True
        ) as conn:
            row = conn.execute(
                "select enabled, notifications_after, changed_by, changed_at "
                "from service_settings where key = %s",
                (key,),
            ).fetchone()
    except (psycopg.Error, ValueError) as exc:
        raise SettingsUnavailable(type(exc).__name__) from exc
    if row is None:
        return None
    if type(row[0]) is not bool:
        raise SettingsUnavailable("InvalidBoolean")
    return BooleanSetting(row[0], row[1], str(row[2]), row[3])
