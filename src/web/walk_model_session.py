"""The search and selected-item check share one bounded auditor model session."""

from __future__ import annotations

import threading

from .server_limits import walk_model_gate


class ModelSession:
    def __init__(self) -> None:
        self.busy: set[int] = set()
        self.guard = threading.Lock()
        self.gate = walk_model_gate()
