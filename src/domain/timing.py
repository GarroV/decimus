"""Server visit timestamps; elapsed time is derived once from the primary pair."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Время проверки должно содержать часовой пояс")
    return stamp.astimezone(UTC)


def duration_seconds(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    """No start or no successful finish means unknown, never zero or an estimate."""
    start, end = parse_timestamp(started_at), parse_timestamp(finished_at)
    if start is None or end is None:
        return None
    elapsed = (end - start).total_seconds()
    if elapsed < 0:
        raise ValueError("Конец проверки раньше начала")
    return elapsed
