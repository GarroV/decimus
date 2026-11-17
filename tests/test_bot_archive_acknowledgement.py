"""A configuration refusal cannot acknowledge a durable archive as complete."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import db, domain
from src.bot import sidecar
from src.bot.routers.finish import archive
from src.domain import completion
from src.domain.revision import revision

CHAT = 8418


def delivered_job(tmp_path: Path):
    inspection = domain.start_inspection(CHAT, unit="Белград-1", kind="planned", report_lang="ru")
    sidecar.mark_handed_over(CHAT, len(inspection.findings))
    job = completion.snapshot(CHAT, inspection.run_id, revision(inspection))
    pdf = tmp_path / "synthetic.pdf"
    pdf.write_bytes(b"synthetic delivered PDF")
    report = completion.prepare(CHAT, job, pdf, {})
    completion.mark(CHAT, job, "delivered")
    return job, report


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", ["push_inspection", "upload_photos", "upload_report"])
async def test_config_refusal_keeps_delivered_snapshot_pending(
    domain_env: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str
):
    job, report = delivered_job(tmp_path)
    monkeypatch.setattr(db, "push_inspection", lambda *args, **kwargs: "synthetic-inspection")
    monkeypatch.setattr(db, "upload_photos", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        db,
        "upload_report",
        lambda *args, **kwargs: SimpleNamespace(
            storage_path="synthetic", size_bytes=1, already=False
        ),
    )

    def unavailable(*args, **kwargs):
        raise db.ConfigError("synthetic configuration refusal")

    monkeypatch.setattr(db, refused, unavailable)
    acknowledged = await archive(
        SimpleNamespace(answer=AsyncMock()),
        CHAT,
        {},
        "ru",
        allow_missing=True,
        source_settings=job,
        report=report,
    )
    # This is the caller's acknowledgement contract: only True retires the job.
    if acknowledged:
        completion.mark(CHAT, job, "archived")
    assert not acknowledged
    pending = completion.pending()
    assert len(pending) == 1 and pending[0][0] == CHAT
    assert report.read_bytes() == b"synthetic delivered PDF"


@pytest.mark.asyncio
async def test_explicit_legacy_mode_without_database_retains_its_api_behavior(monkeypatch):
    def not_configured(*args, **kwargs):
        raise db.ConfigError("synthetic no-database mode")

    monkeypatch.setattr(db, "push_inspection", not_configured)
    assert await archive(SimpleNamespace(answer=AsyncMock()), CHAT, {}, "ru", allow_missing=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", ["upload_photos", "upload_report"])
async def test_failed_storage_is_not_success_even_for_a_legacy_caller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str
):
    report = tmp_path / "synthetic.pdf"
    report.write_bytes(b"synthetic PDF")
    monkeypatch.setattr(db, "push_inspection", lambda *args, **kwargs: "synthetic-inspection")
    monkeypatch.setattr(db, "upload_photos", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        db,
        "upload_report",
        lambda *args, **kwargs: SimpleNamespace(
            storage_path="synthetic", size_bytes=1, already=False
        ),
    )

    def unavailable(*args, **kwargs):
        raise db.ConfigError("synthetic storage configuration refusal")

    monkeypatch.setattr(db, refused, unavailable)
    assert not await archive(
        SimpleNamespace(answer=AsyncMock()),
        CHAT,
        {},
        "ru",
        allow_missing=True,
        report=report,
    )
