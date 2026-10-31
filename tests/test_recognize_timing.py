"""#1253: deterministic clocks, provider failures, and concurrent request isolation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from openai import OpenAIError
from test_recognize_client import _SCHEMA, _FakeResponse, _settings

from src.recognize import client, timing
from src.recognize.errors import ModelUnavailable


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms * 1_000_000


def test_nested_scopes_and_exceptions_restore_previous_timer(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(timing, "perf_counter_ns", clock)
    with timing.collect() as outer:
        with timing.measure("prepare"):
            clock.advance(2)
        with timing.collect() as inner:
            with timing.measure("model"):
                clock.advance(7)
            assert inner.report() == {"ms": 7, "model_ms": 7, "timings_ms": {"model": 7}}
        with pytest.raises(ValueError), timing.measure("model"):
            clock.advance(3)
            raise ValueError("synthetic failure")
        assert outer.report() == {"ms": 12, "model_ms": 3, "timings_ms": {"prepare": 2, "model": 3}}
    assert timing.report() == {"ms": 0, "model_ms": 0, "timings_ms": {}}


def test_concurrent_requests_never_share_stage_values():
    barrier = Barrier(2)

    def run(name):
        with timing.collect() as request:
            with timing.measure(name):
                barrier.wait(timeout=5)
            return request.report()["timings_ms"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["first", "second"]))
    assert set(results[0]) == {"first"}
    assert set(results[1]) == {"second"}


@pytest.mark.parametrize("fail", [False, True])
def test_provider_duration_is_measured_on_success_and_failure(monkeypatch, fail):
    clock = Clock()
    monkeypatch.setattr(timing, "perf_counter_ns", clock)

    def provide(**kwargs):
        clock.advance(11)
        if fail:
            raise OpenAIError("synthetic failure")
        return _FakeResponse(output_text='{"records": []}')

    fake = SimpleNamespace(responses=SimpleNamespace(create=provide))
    monkeypatch.setattr(client, "_new_client", lambda settings: fake)
    monkeypatch.setattr(client, "_note", lambda *a, **kw: None)
    with timing.collect() as request:

        def call():
            return client.ask_model(
                kind="recognize",
                instructions="synthetic",
                question="synthetic",
                schema=_SCHEMA,
                photo=None,
                settings=_settings(),
            )

        if fail:
            with pytest.raises(ModelUnavailable):
                call()
        else:
            assert call().payload == {"records": []}
        assert request.report() == {"ms": 11, "model_ms": 11, "timings_ms": {"model": 11}}
