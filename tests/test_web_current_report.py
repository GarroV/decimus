"""PDF выдаётся по актуальному снимку; старые файлы остаются историей."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock
from typing import Any

import pytest
from test_web_app import карточка, шапка

from src.db import busy_lock
from src.db.errors import StorageError
from src.db.models import InfoRow, InspectionDetail
from src.db.previews import ReportPhoto
from src.db.reach import Reach
from src.db.reports import ReportRef
from src.report import current_pdf as service
from src.report.letters import LetterError
from src.web import inspections as screen

REACH = Reach("HQ", None, None)


@pytest.fixture
def reports(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    detail = карточка(replace(шапка(), accepted_at="2026-10-30T12:00:00+00:00"))
    old = ReportRef("s3://bucket/old.pdf", "application/pdf", 10, datetime.now(UTC))
    state: dict[str, Any] = {
        "detail": detail,
        "ref": old,
        "builds": [],
        "uploads": [],
        "photo_keys": [],
        "photos": (
            ReportPhoto(
                "photo-1", detail.findings[0].n, None, "s3://bucket/original", "s3://bucket/preview"
            ),
        ),
    }
    monkeypatch.setattr(service.queries, "get_inspection", lambda *_a, **_k: state["detail"])
    monkeypatch.setattr(screen, "load_report", lambda *_a, **_k: state["ref"])
    monkeypatch.setattr(service.reports, "latest_report", lambda *_a, **_k: state["ref"])
    monkeypatch.setattr(service.previews, "report_photos", lambda *_a, **_k: state["photos"])
    monkeypatch.setattr(service, "load_storage_settings", lambda: object())

    class Storage:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def get(self, _key: str) -> bytes:
            state["photo_keys"].append(_key)
            return b"image"

    monkeypatch.setattr(service, "S3PhotoStorage", Storage)
    monkeypatch.setattr(service, "letter_sources", lambda: object())
    monkeypatch.setattr(busy_lock, "try_hold", lambda *_a: busy_lock.Hold(True, True))

    def build(detail: InspectionDetail, **kwargs: object) -> bytes:
        state["builds"].append((detail, kwargs))
        return b"%PDF-current"

    def upload(_id: str, **kwargs: Any) -> None:
        state["uploads"].append(kwargs)
        state["ref"] = ReportRef(
            f"s3://bucket/inspections/{_id}/reports/{kwargs['source_fingerprint']}/new.pdf",
            "application/pdf",
            len(kwargs["data"]),
            datetime.now(UTC),
        )

    monkeypatch.setattr(service.detail_pdf, "build_bytes", build)
    monkeypatch.setattr(service.reports, "upload_report", upload)
    return state


@pytest.mark.parametrize("change", ["text", "level", "header", "info"])
def test_same_snapshot_reuses_pdf_and_changed_content_creates_new_revision(
    reports: dict[str, Any],
    change: str,
) -> None:
    first = screen.ensure_report(reports["detail"], reach=REACH)
    assert screen.ensure_report(reports["detail"], reach=REACH) == first
    assert len(reports["builds"]) == 1
    detail = reports["detail"]
    if change in ("text", "level"):
        finding = replace(
            detail.findings[0], **{change: "D2" if change == "level" else "Changed observation"}
        )
        reports["detail"] = replace(detail, findings=(finding, *detail.findings[1:]))
    elif change == "header":
        reports["detail"] = replace(
            detail, inspection=replace(detail.inspection, auditor="Updated auditor")
        )
    else:
        reports["detail"] = replace(detail, info=(InfoRow("INF03", "Updated answer"),))
    second = screen.ensure_report(detail, reach=REACH)  # canonical DB snapshot wins
    assert second.storage_path != first.storage_path
    assert len(reports["uploads"]) == 2
    assert reports["builds"][-1][0] == reports["detail"]


def test_changed_photo_and_info_photo_are_included_and_invalidate_report(
    reports: dict[str, Any],
) -> None:
    first = screen.ensure_report(reports["detail"], reach=REACH)
    reports["photos"] = (replace(reports["photos"][0], preview_path="s3://bucket/new-preview"),)
    changed_photo = screen.ensure_report(reports["detail"], reach=REACH)
    assert changed_photo.storage_path != first.storage_path
    reports["photos"] += (ReportPhoto("info-photo", None, "INF03", "s3://bucket/info", None),)
    second = screen.ensure_report(reports["detail"], reach=REACH)
    assert first.storage_path != second.storage_path
    assert reports["builds"][-1][1]["info_photos"] == {"INF03": [b"image"]}


def test_builder_failure_never_returns_old_pdf(
    reports: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_a: object, **_k: object) -> bytes:
        raise LetterError("Cannot build")

    monkeypatch.setattr(service.detail_pdf, "build_bytes", refuse)
    with pytest.raises(LetterError, match="Cannot build"):
        screen.ensure_report(reports["detail"], reach=REACH)
    assert not reports["uploads"]


def test_changed_during_render_is_not_published(
    reports: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def concurrent_edit(*_a: object, **_k: object) -> bytes:
        detail = reports["detail"]
        reports["detail"] = replace(detail, inspection=replace(detail.inspection, auditor="new"))
        return b"%PDF-stale"

    monkeypatch.setattr(service.detail_pdf, "build_bytes", concurrent_edit)
    with pytest.raises(StorageError, match="изменилась"):
        screen.ensure_report(reports["detail"], reach=REACH)
    assert not reports["uploads"]


def test_legacy_uses_original_and_inaccessible_inspection_is_refused(
    reports: dict[str, Any],
) -> None:
    detail = reports["detail"]
    reports["detail"] = replace(detail, inspection=replace(detail.inspection, origin="legacy"))
    assert screen.ensure_report(reports["detail"], reach=REACH) == reports["ref"]
    assert not reports["builds"]
    reports["detail"] = None
    with pytest.raises(StorageError, match="недоступна"):
        screen.ensure_report(detail, reach=REACH)
    assert not reports["uploads"]


def test_concurrent_request_does_not_build_twice(
    reports: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, finish = Event(), Event()
    lock = Lock()
    build: Callable[..., bytes] = service.detail_pdf.build_bytes

    class Hold:
        shared = True

        def __init__(self) -> None:
            self.acquired = lock.acquire(blocking=False)

        def release(self) -> None:
            if self.acquired:
                self.acquired = False
                lock.release()

    def slow_build(*args: Any, **kwargs: Any) -> bytes:
        started.set()
        assert finish.wait(5)
        return build(*args, **kwargs)

    monkeypatch.setattr(busy_lock, "try_hold", lambda *_a: Hold())
    monkeypatch.setattr(service.detail_pdf, "build_bytes", slow_build)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(screen.ensure_report, reports["detail"], reach=REACH)
        assert started.wait(5)
        try:
            with pytest.raises(StorageError, match="уже собирается"):
                screen.ensure_report(reports["detail"], reach=REACH)
        finally:
            finish.set()
        ref = future.result(timeout=5)
    assert screen.ensure_report(reports["detail"], reach=REACH) == ref
    assert len(reports["builds"]) == 1


def test_download_rechecks_source_before_answering_not_modified(
    reports: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from web_harness import войти, подменить_двери, собрать

    подменить_двери(monkeypatch, tenant="HQ", role="admin")
    monkeypatch.setattr(screen, "load_card", lambda *_a, **_k: reports["detail"])
    monkeypatch.setattr(screen, "report_bytes", lambda _ref: b"%PDF-current")
    path = f"/inspections/{reports['detail'].inspection.id}/report"
    with собрать(tenant="HQ").test_client() as client:
        assert войти(client).status_code == 302
        first = client.get(path)
        assert first.status_code == 200
        old_etag = first.headers["ETag"]
        detail = reports["detail"]
        reports["detail"] = replace(
            detail, inspection=replace(detail.inspection, auditor="changed")
        )
        second = client.get(path, headers={"If-None-Match": old_etag})
        assert second.status_code == 200
        assert second.headers["ETag"] != old_etag
        third = client.get(path, headers={"If-None-Match": second.headers["ETag"]})
        assert third.status_code == 304
    assert len(reports["builds"]) == 2


def test_unrelated_build_sha_does_not_invalidate_existing_report(
    reports: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUILD_SHA", "release-one")
    first = screen.ensure_report(reports["detail"], reach=REACH)
    monkeypatch.setenv("BUILD_SHA", "release-two")
    second = screen.ensure_report(reports["detail"], reach=REACH)
    assert first.storage_path == second.storage_path
    assert len(reports["uploads"]) == 1


def test_pdf_prefers_original_and_falls_back_to_preview(reports: dict[str, Any]) -> None:
    screen.ensure_report(reports["detail"], reach=REACH)
    assert reports["photo_keys"] == ["original"]
    reports["photos"] = (replace(reports["photos"][0], storage_path=None),)
    screen.ensure_report(reports["detail"], reach=REACH)
    assert reports["photo_keys"] == ["original", "preview"]


def test_changed_during_upload_refuses_snapshot_but_keeps_archive(
    reports: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = service.reports.upload_report

    def changed_after_upload(*args: Any, **kwargs: Any) -> None:
        upload(*args, **kwargs)
        detail = reports["detail"]
        reports["detail"] = replace(
            detail, inspection=replace(detail.inspection, unit_name="Changed while uploading")
        )

    monkeypatch.setattr(service.reports, "upload_report", changed_after_upload)
    with pytest.raises(StorageError, match="изменилась"):
        screen.ensure_report(reports["detail"], reach=REACH)
    assert len(reports["uploads"]) == 1
    archived = reports["ref"]
    monkeypatch.setattr(service.reports, "upload_report", upload)
    current = screen.ensure_report(reports["detail"], reach=REACH)
    assert current != archived
    assert len(reports["uploads"]) == 2


def test_photo_adapter_change_invalidates_existing_report(
    reports: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    adapter = tmp_path / "current_pdf.py"
    adapter.write_text("photo adapter version one", encoding="utf-8")
    monkeypatch.setattr(service, "__file__", str(adapter))
    first = screen.ensure_report(reports["detail"], reach=REACH)
    adapter.write_text("photo adapter version two", encoding="utf-8")
    second = screen.ensure_report(reports["detail"], reach=REACH)
    assert first.storage_path != second.storage_path
    assert len(reports["uploads"]) == 2
