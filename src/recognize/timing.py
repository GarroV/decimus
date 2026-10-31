"""#1253: monotonic request-local timing; never captures input or model output.

Stages may nest (prepare/model/parse are inside propose). Values describe elapsed
wall time, including provider retries; they are not token usage or additive totals.
No shared mutable timer: concurrent searches and nested scopes remain isolated.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import TypedDict


class TimingReport(TypedDict):
    ms: int
    model_ms: int
    timings_ms: dict[str, int]


@dataclass
class Timings:
    started_ns: int = field(default_factory=lambda: perf_counter_ns())
    stages_ns: dict[str, int] = field(default_factory=dict)

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        started = perf_counter_ns()
        try:
            yield
        finally:
            self.stages_ns[name] = self.stages_ns.get(name, 0) + max(0, perf_counter_ns() - started)

    def report(self) -> TimingReport:
        stages = {name: elapsed // 1_000_000 for name, elapsed in self.stages_ns.items()}
        return {
            "ms": max(0, perf_counter_ns() - self.started_ns) // 1_000_000,
            "model_ms": stages.get("model", 0),
            "timings_ms": stages,
        }


_current: ContextVar[Timings | None] = ContextVar("recognize_timings", default=None)


@contextmanager
def collect() -> Iterator[Timings]:
    timing = Timings()
    token = _current.set(timing)
    try:
        yield timing
    finally:
        _current.reset(token)


@contextmanager
def measure(name: str) -> Iterator[None]:
    timing = _current.get()
    if timing is None:
        yield
    else:
        with timing.measure(name):
            yield


def report() -> TimingReport:
    timing = _current.get()
    return timing.report() if timing is not None else {"ms": 0, "model_ms": 0, "timings_ms": {}}
