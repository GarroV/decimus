"""Opt-in synthetic Flask/domain/engine write benchmark; never starts a server."""

from __future__ import annotations

import json
import logging
import math
import os
import platform
import statistics
from pathlib import Path
from time import perf_counter_ns

import pytest
from test_web_walk import АУДИТОР
from test_web_walk_write import Клиент, _jpeg, клиент  # noqa: F401

from src.domain import get_state, start_inspection
from src.domain.revisions import finding_revision
from src.web.walk_write_timing import logger

# ruff: noqa: F811


def test_synthetic_write_benchmark(клиент: Клиент, caplog):
    target = os.environ.get("WALK_WRITE_BENCHMARK_REPORT")
    if not target:
        pytest.skip("Opt in with WALK_WRITE_BENCHMARK_REPORT pointing to a private report")
    output = Path(target).expanduser().resolve()
    root = Path(__file__).resolve().parents[1]
    assert not output.is_relative_to(root), "Benchmark artifacts belong outside the repository"
    count = int(os.environ.get("WALK_WRITE_BENCHMARK_N", "40"))
    warmup = 5
    assert 10 <= count <= 80
    caplog.set_level(logging.INFO, logger=logger.name)
    ref = клиент.ссылка()
    samples = {name: [] for name in ("create", "edit", "info", "photo")}

    def sample(name, call, expected, index):
        caplog.clear()
        started = perf_counter_ns()
        reply = call()
        elapsed = (perf_counter_ns() - started) / 1_000_000
        assert reply.status_code == expected, reply.get_json()
        logged = [record for record in caplog.records if record.name == logger.name]
        assert len(logged) == 1
        timing = logged[0].args[2]
        if index >= warmup:
            samples[name].append(
                {"total_client_ms": elapsed, "http_view_ms": timing["ms"], **timing["timings_ms"]}
            )
        return reply

    for index in range(warmup + count):
        start_inspection(АУДИТОР, unit="Synthetic benchmark", kind="planned", report_lang="ru")
        run = get_state(АУДИТОР).run_id
        sample(
            "create",
            lambda run=run: клиент.запись(
                op="add",
                code="CLN05",
                level="D1",
                zone="hot_kitchen",
                text="Synthetic human observation",
                words="Synthetic words",
                photos=[ref],
                run_id=run,
            ),
            200,
            index,
        )
        revision = finding_revision(get_state(АУДИТОР).findings[0])
        sample(
            "edit",
            lambda run=run, revision=revision, index=index: клиент.запись(
                op="edit",
                n=1,
                text="Synthetic changed description",
                reading_c=0,
                source_revision=revision,
                request_id=f"{index:032x}",
                run_id=run,
            ),
            200,
            index,
        )
        sample(
            "info",
            lambda run=run: клиент.сведение(
                code="INF08", value="Synthetic visit answer", run_id=run
            ),
            200,
            index,
        )
        raw = _jpeg((index * 5 % 256, index * 3 % 256, index * 7 % 256))
        sample("photo", lambda raw=raw: клиент.кадр(raw), 201, index)

    def summary(rows):
        result = {}
        for field in rows[0]:
            ordered = sorted(row[field] for row in rows)
            result[field] = {
                "median": round(statistics.median(ordered), 3),
                "p95": round(ordered[math.ceil(len(ordered) * 0.95) - 1], 3),
            }
        return result

    report = {
        "samples_per_operation": count,
        "warmup_per_operation": warmup,
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "scope": "Flask test_client + actual domain/engine, synthetic temporary state",
        "excluded": ["network", "Telegram", "database", "LLM", "browser", "image compression"],
        "photo_payload": "32x24 synthetic JPEG, unique content per sample; no client compression",
        "stage_resolution_ms": 1,
        "stages_additive": False,
        "summary_ms": {name: summary(rows) for name, rows in samples.items()},
        "samples_ms": samples,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
