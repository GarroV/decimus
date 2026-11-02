"""Explicit country To: override. None means legacy defaults, empty means no recipients.

Independent of contract contacts, remembered prescription addresses and global CC.
Application reads only from HQ; administrator writes. No sending or PII in logs.
"""

from __future__ import annotations

import psycopg

from .config import check_environment, load_retraction_settings
from .errors import DbError
from .pool import connection
from .prescriptions import parse_recipients


def read(country: str) -> str | None:
    try:
        with connection(check_environment().dsn) as conn:
            row = conn.execute(
                "select recipients from country_mailing_recipients where country = %s",
                (country,),
            ).fetchone()
    except psycopg.Error as exc:
        raise DbError("Country mailing recipients could not be read") from exc
    return None if row is None else str(row[0])


def save(country: str, raw: str, *, actor: str, reset: bool = False) -> None:
    recipients = "" if reset else parse_recipients(raw).lower()
    if not actor.strip():
        raise ValueError("An actor is required")
    try:
        with psycopg.connect(load_retraction_settings().dsn) as conn:
            if reset:
                conn.execute(
                    "delete from country_mailing_recipients where country = %s", (country,)
                )
            else:
                conn.execute(
                    "insert into country_mailing_recipients (country, recipients, updated_by) "
                    "values (%s, %s, %s) on conflict (country) do update set "
                    "recipients = excluded.recipients, updated_by = excluded.updated_by, "
                    "updated_at = now()",
                    (country, recipients, actor),
                )
    except psycopg.Error as exc:
        raise DbError("Country mailing recipients were not changed") from exc
