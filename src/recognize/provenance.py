"""Photo evidence indices from untrusted model/client data; no ownership decisions."""

from __future__ import annotations

from typing import Any


def frame_indices(value: Any, count: int) -> tuple[int, ...] | None:
    """All valid, unique indices in the actual frame set, or unknown (None).

    Missing/malformed evidence must never mean 'all frames'. Empty evidence is
    valid but cannot supply the photo required to save an additional finding.
    """
    if not isinstance(value, (list, tuple)):
        return None
    if any(isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < count for i in value):
        return None
    if len(set(value)) != len(value):
        return None
    return tuple(value)
